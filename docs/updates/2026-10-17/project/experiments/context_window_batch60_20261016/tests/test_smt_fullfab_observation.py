"""Causality, qualification and snapshot tests; no optimizer or model calls."""
from copy import copy, deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from src.smt_fullfab.environment import FullFabEnvironment, plan_from_action
from src.smt_fullfab.observation import build_problem


def small_inflight_environment(force_piece_pm=False):
    env=FullFabEnvironment(seed=1701,window_seconds=120)
    chosen=None
    for mid in sorted(env.physical):
        if env.machines[mid].cascading:
            continue
        for lid in env.eligible(mid):
            lot=env.lots[lid]; step=env._step(lot); route=env.routes[lot['route']].steps
            if step.batch_min==1 and lot['step']+1<len(route) and route[lot['step']+1].transport_time:
                chosen=(mid,lid); break
        if chosen:
            break
    mid,lid=chosen
    if force_piece_pm:
        # Explicit synthetic threshold boundary, not an official source run.
        assert env.pm_counters[mid]
        env.pm_counters[mid][0]['remaining']=1
    plan=plan_from_action(env,{'dispatches':[{'machine':mid,'lot_ids':[lid]}],'wait_seconds':0},'review-0',valid_seconds=120)
    plan['holds']=[{'machine':other,'until':120,'reason':'review controlled fixture wait'} for other in sorted(env.physical) if other!=mid]
    env.commit_plan(plan)
    env._run_planned_now()
    return env,mid,lid


class ObservationTests(unittest.TestCase):
    def test_private_future_times_and_rng_queue_do_not_change_problem(self):
        env,mid,lid=small_inflight_environment()
        first=build_problem(env,lookahead_depth=3)
        jid=next(jid for jid,job in env.jobs.items() if lid in job['lots'])
        env.jobs[jid]['lot_end']+=10000
        env.jobs[jid]['process_end']+=20000
        env.machine_state[mid]['ready']+=30000
        # Future queue timestamps and private random seed are not observations.
        env.seed+=900
        env.q=[(q[0]+9999,q[1],q[2],q[3]) for q in env.q]
        for event in env.trace:
            if event['kind']=='dispatch':
                for field in ('processing_seconds','cadence_seconds','transport_seconds','process_end','lot_end','machine_ready'):
                    event[field]+=40000
        second=build_problem(env,lookahead_depth=3)
        self.assertEqual(first,second)
        encoded=json.dumps(second)
        self.assertNotIn('processing_key',encoded)
        self.assertNotIn('first_time',encoded)
        self.assertNotIn('seed',second)
        self.assertNotIn('q',second)

    def test_public_expected_remaining_and_active_flags(self):
        env,mid,lid=small_inflight_environment()
        problem=build_problem(env)
        machine=next(m for m in problem['machines'] if m['machine']==mid)
        self.assertTrue(machine['currently_busy'])
        self.assertFalse(machine['currently_down'])
        self.assertGreater(machine['available_at'],env.t)
        self.assertEqual(len(machine['processing_until']),1)
        nextop=next(o for o in problem['operations'] if o['lot_id']==lid)
        self.assertGreater(nextop['release_time'],env.t)
        self.assertTrue(nextop['conditional'])

    def test_active_repair_future_duration_is_not_exposed(self):
        env,mid,_=small_inflight_environment()
        calendar=next(key for key,value in env.calendars.items() if value['machine']==mid)
        env._calendar({'key':calendar,'n':0})
        first=build_problem(env)
        env.machine_state[mid]['down_until']+=20000
        env.machine_state[mid]['ready']+=20000
        for job in env.jobs.values():
            if job['machine']==mid:
                job['process_end']+=20000
                job['lot_end']+=20000
        for event in env.trace:
            if event['kind']=='downtime':
                event['duration']+=20000
                event['blocked_until']+=20000
                event['machine_ready']+=20000
        self.assertEqual(first,build_problem(env))
        observed=next(m for m in first['machines'] if m['machine']==mid)
        self.assertTrue(observed['currently_down'])

    def test_piece_pm_uses_mean_not_private_sample(self):
        env,mid,_=small_inflight_environment(force_piece_pm=True)
        first=build_problem(env)
        dispatched=next(e for e in env.trace if e['kind']=='dispatch' and e['machine']==mid)
        self.assertTrue(dispatched['piece_pm'])
        for pm in dispatched['piece_pm']:
            pm['duration']+=100000
        env.machine_state[mid]['ready']+=100000
        self.assertEqual(first,build_problem(env))

    def test_virtual_delay_is_explicit_conditional_transfer(self):
        env=FullFabEnvironment(window_seconds=120)
        lid=next(lid for lid,l in env.lots.items() if l['status']=='waiting' and
                 not any(mid in env.physical for mid in env.family_machines[env._step(l).family]))
        focused=copy(env);focused.lots={lid:env.lots[lid]}
        problem=build_problem(focused,lookahead_depth=2)
        first=problem['operations'][0]
        self.assertTrue(first['initial_virtual_predecessors'])
        self.assertGreater(first['release_time'],env.t)
        self.assertTrue(first['conditional'])
        self.assertTrue(all(mid in env.physical for mid in first['eligible_machines']))
        self.assertIn('sampling_percent',first['initial_virtual_predecessors'][0])

    def test_future_binding_retains_same_machine_relationship(self):
        env=FullFabEnvironment(window_seconds=120)
        lid=next(lid for lid,l in env.lots.items() if l['status']=='waiting' and env._step(l).lot_to_lens_dedication is not None)
        focused=copy(env);focused.lots={lid:env.lots[lid]}
        problem=build_problem(focused,lookahead_depth=30)
        origin=env._step(env.lots[lid]); target=origin.lot_to_lens_dedication
        ops={o['step']:o for o in problem['operations']}
        self.assertIn(target,ops)
        self.assertEqual(ops[target]['same_machine_as'],ops[origin.order]['operation_id'])

    def test_missing_historical_binding_is_explicit(self):
        env=FullFabEnvironment(window_seconds=120)
        problem=build_problem(env,lookahead_depth=2)
        unknown=[o for o in problem['operations'] if o.get('qualification_uncertain')]
        self.assertTrue(unknown)
        self.assertTrue(all('binding_origin_step' in o for o in unknown))

    def test_problem_read_does_not_mutate_simulator(self):
        env,_,_=small_inflight_environment()
        before=deepcopy((env.lots,env.machine_state,env.jobs,env.waiting,env.processing_by_machine,env.trace,env.q))
        build_problem(env)
        after=(env.lots,env.machine_state,env.jobs,env.waiting,env.processing_by_machine,env.trace,env.q)
        self.assertEqual(before,after)

    def test_snapshot_preserves_private_state_and_public_prediction(self):
        env,mid,lid=small_inflight_environment()
        expected=build_problem(env)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'checkpoint.json'
            env.snapshot(path)
            recovered=FullFabEnvironment.from_snapshot(path)
        self.assertEqual(env.machine_state,recovered.machine_state)
        self.assertEqual(env.jobs,recovered.jobs)
        self.assertEqual(env.waiting,recovered.waiting)
        self.assertEqual(env.processing_by_machine,recovered.processing_by_machine)
        self.assertEqual(expected,build_problem(recovered))
        # Advance identical fixed plans only one simulated second, including a
        # genuinely running production job. Snapshot control metadata differs.
        env.advance_plan(1); recovered.advance_plan(1)
        self.assertEqual(env.lots,recovered.lots)
        self.assertEqual(env.machine_state,recovered.machine_state)
        self.assertEqual(env.jobs,recovered.jobs)
        self.assertEqual(env.q,recovered.q)


if __name__=='__main__':
    unittest.main()
