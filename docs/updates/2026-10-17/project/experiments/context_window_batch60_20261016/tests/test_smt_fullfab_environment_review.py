"""Independent lightweight review of coverage, plan validation and checkpointing."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from src.smt_fullfab.environment import FullFabEnvironment,plan_from_action
from tests.test_smt_fullfab_observation import small_inflight_environment


class EnvironmentReviewTests(unittest.TestCase):
    def test_observed_skip_invalidates_future_or_nonhead_task_before_waiting(self):
        # Isolate the public-state transition which the independent opportunity
        # replay exposed in A_1701_1h_incumbent_v2; no physics mocking is needed.
        for nonhead in (False, True):
            for cause in ('skip', 'revisit', 'done'):
                with self.subTest(nonhead=nonhead, cause=cause):
                    env=FullFabEnvironment.__new__(FullFabEnvironment)
                    env.t=5.;env.executed_tasks=set();env.last_stop=None
                    head={'id':'head','machine':9,'lot_ids':['head'], 'steps':[1],'visits':[1],'not_before':50.}
                    stale={'id':'stale','machine':9,'lot_ids':['stale'], 'steps':[1],'visits':[1],'not_before':100.}
                    env.plan={'version':'v','tasks':([head] if nonhead else [])+[stale],
                              'holds':[{'machine':9,'until':120.,'reason':'submitted wait'}]}
                    env.lots={'head':{'status':'waiting','step':0,'visits':{'1':1}},
                              'stale':{'status':'done' if cause=='done' else 'waiting',
                                       'step':1 if cause=='skip' else 0,'visits':{'1':2 if cause=='revisit' else 1}}}
                    events=[];env._emit=lambda kind,**kw:events.append({'kind':kind,**kw})
                    original=deepcopy(env.plan)
                    self.assertFalse(env._run_planned_now())
                    self.assertEqual(env.last_stop,{'reason':'plan_invalidated','task':'stale'})
                    self.assertEqual(events[0]['kind'],'plan_invalidated')
                    self.assertEqual(env.plan,original)
                    self.assertEqual(env.executed_tasks,set())

    def test_no_plan_never_dispatches_production(self):
        env=FullFabEnvironment(window_seconds=120)
        stop=env.advance_plan(1)
        self.assertEqual(stop['reason'],'uncovered_demand')
        self.assertEqual(env.t,0)
        self.assertFalse([e for e in env.trace if e['kind']=='dispatch' and e['machine'] in env.physical])

    def test_task_outside_plan_validity_is_rejected(self):
        env,_,_=small_inflight_environment()
        plan=deepcopy(env.plan)
        plan['version']='invalid-outside'
        plan['tasks'][0]['not_before']=plan['valid_until']
        with self.assertRaisesRegex(ValueError,'planned start'):
            env.commit_plan(plan)

    def test_started_job_history_survives_plan_replacement(self):
        env,mid,lid=small_inflight_environment()
        before=deepcopy(env.jobs)
        started=deepcopy([e for e in env.trace if e['kind']=='dispatch' and e['machine']==mid])
        replacement=plan_from_action(env,{'dispatches':[],'wait_seconds':120},'replacement',valid_seconds=120)
        env.commit_plan(replacement)
        self.assertEqual(before,env.jobs)
        self.assertEqual(started,[e for e in env.trace if e['kind']=='dispatch' and e['machine']==mid])
        self.assertEqual(env.lots[lid]['status'],'processing')

    def test_snapshot_rejects_state_tampering(self):
        env,mid,_=small_inflight_environment()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'snapshot.json'; env.snapshot(path)
            value=json.loads(path.read_text())
            value['state']['machine_state'][str(mid)]['setup']='tampered'
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'hash mismatch'):
                FullFabEnvironment.from_snapshot(path)

    def test_snapshot_preserves_completed_task_identity(self):
        env,_,_=small_inflight_environment()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'snapshot.json';env.snapshot(path)
            restored=FullFabEnvironment.from_snapshot(path)
        self.assertEqual(env.executed_tasks,restored.executed_tasks)
        self.assertEqual(env.plan_versions,restored.plan_versions)
        self.assertEqual(env._pending(),restored._pending())
        with self.assertRaisesRegex(ValueError,'new string'):
            restored.commit_plan(deepcopy(env.plan))

    def test_frozen_task_cannot_be_dropped(self):
        env=FullFabEnvironment(window_seconds=120)
        mid=next(mid for mid in sorted(env.physical) if any(env._step(env.lots[lid]).batch_min==1 for lid in env.eligible(mid)))
        lid=next(lid for lid in env.eligible(mid) if env._step(env.lots[lid]).batch_min==1)
        plan=plan_from_action(env,{'dispatches':[{'machine':mid,'lot_ids':[lid]}],'wait_seconds':0},'frozen',valid_seconds=120)
        plan['tasks'][0]['not_before']=10
        plan['freeze_until']=60
        env.commit_plan(plan)
        revised=deepcopy(plan);revised['version']='drops-frozen';revised['tasks']=[]
        with self.assertRaisesRegex(ValueError,'frozen'):
            env.commit_plan(revised)

    def test_frozen_delayed_task_can_retain_past_earliest_start(self):
        env=FullFabEnvironment(window_seconds=120)
        mid=next(mid for mid in sorted(env.physical) if any(env._step(env.lots[lid]).batch_min==1 for lid in env.eligible(mid)))
        lid=next(lid for lid in env.eligible(mid) if env._step(env.lots[lid]).batch_min==1)
        plan=plan_from_action(env,{'dispatches':[{'machine':mid,'lot_ids':[lid]}],'wait_seconds':30},'frozen-delayed',valid_seconds=120)
        plan['freeze_until']=60
        env.commit_plan(plan)
        env.advance_plan(5)
        revised=deepcopy(plan);revised['version']='retained-frozen';revised['created_at']=env.t
        env.commit_plan(revised)
        self.assertEqual(plan['tasks'],env.plan['tasks'])


if __name__=='__main__':
    unittest.main()
