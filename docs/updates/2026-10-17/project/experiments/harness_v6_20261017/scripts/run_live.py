"""Registered command-only trajectory entrypoint; offline mode is never results."""
import argparse
import json
import hashlib
import math
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from harness_v6 import registration
from harness_v6.checkpoint import atomic_write
from harness_v6.contracts import digest
from harness_v6.snapshot import canonical, production_prefix, estimate_tokens, tiktoken_counter
from harness_v6.cycle import CycleConfig, DriftRule
from harness_v6.groups import config_for
from harness_v6.live import LiveRun
from harness_v6.session import Budget
from harness_v6.codex_runner import CodexRunner
from harness_v6.synthetic import SyntheticFactory, ScriptedRunner, prompt_action


def totals(run, *, steady_only=False):
    values = {}
    for hour,row in run.metrics.buckets.items():
        if steady_only and hour < run.metrics.exclude_first_hours:
            continue
        for k,v in row.items(): values[k] = values.get(k, 0) + v
    for key in ('throughput', 'weighted_tardiness', 'avoidable_idle_seconds', 'explicit_wait_idle_seconds', 'failures', 'unknown_usage'):
        values.setdefault(key, 0)
    return run.metrics.derived(values)


def execute(args):
    reg = registration.load(args.registration, results=not args.dry_run_scripted)
    if bool(reg['dry_run']) != args.dry_run_scripted:
        raise ValueError('registration dry_run must match --dry-run-scripted')
    if args.group not in reg['groups'] or not 1 <= args.trajectory <= reg['trajectories_per_group']:
        raise ValueError('unregistered group/trajectory')
    output = Path(args.output).resolve()
    fixture = reg.get('fixture') or os.environ.get('V6_MAC_FIXTURE')
    synthetic = fixture == 'synthetic'
    if synthetic and not args.dry_run_scripted:
        raise ValueError('synthetic factory is never results')
    if not isinstance(reg.get('end_time'), (int,float)) or not math.isfinite(reg['end_time']):
        raise ValueError('end_time must be finite')
    if args.until is not None and not math.isfinite(args.until):
        raise ValueError('until must be finite')
    stop = reg['end_time'] if args.until is None else min(args.until, reg['end_time'])
    seed = reg.get('trajectory_seeds', list(range(1, reg['trajectories_per_group']+1)))[args.trajectory-1]
    identity = dict(registration_hash=digest(reg), group=args.group, trajectory=args.trajectory,
                    dry_run=args.dry_run_scripted, seed=seed)
    manifest_path = output/'run_manifest.json'
    if args.resume:
        manifest = json.loads(manifest_path.read_text())
        if any(manifest.get(k) != v for k,v in identity.items()):
            raise ValueError('resume registration/group/trajectory mismatch')
    elif output.exists() and any(output.iterdir()):
        raise ValueError('output is not empty; use --resume')
    output.mkdir(parents=True, exist_ok=True)
    if synthetic:
        factory = SyntheticFactory(seed)
        routing, machines, counter = [1,2], [1,2], estimate_tokens
        fixture_hash = digest('synthetic-v1')
    else:
        if not fixture: raise ValueError('set registration.fixture or V6_MAC_FIXTURE')
        from harness_v6.factory_v6 import restore, LiveFactory
        blob = Path(fixture).read_bytes(); bundle = json.loads(blob)
        state = bundle[reg.get('fixture_key', 'mixed_702')]
        env = restore(state['state'], state['trace'], data_dir=bundle['data_dir'])
        # Start state remains sealed; subsequent keyed randomness uses the registered seed.
        env.seed = seed
        env.breakdowns = reg.get('breakdowns', reg['stage'] in ('S2','S3','S4'))
        if reg['end_time'] + reg['horizon_seconds'] > env.horizon:
            raise ValueError('fixture horizon must cover end_time + horizon_seconds')
        factory = LiveFactory(env)
        routing, machines, counter = env.manifest['routes'], env.manifest['machines'], tiktoken_counter()
        fixture_hash = hashlib.sha256(blob).hexdigest()
        del blob, bundle, state
    if stop <= factory.now: raise ValueError('until must be after initial time')
    config = config_for(args.group, CycleConfig(stage=reg['stage'], delta=reg['delta_seconds'],
        horizon=reg['horizon_seconds'], delta_min=reg['delta_min_seconds'],
        breakdowns=reg.get('breakdowns', reg['stage'] in ('S2','S3','S4')),
        k_fail=reg['failure']['k_fail'], unknown_usage_cap=reg['failure']['unknown_usage_cap'],
        hourly_cost_cap=reg.get('per_sim_hour_token_cap'),
        segment_seconds=reg.get('segment_seconds',3600), segment_cycles=reg.get('segment_cycles',60)))
    budget = Budget(**reg.get('session_budget', {}))
    if args.dry_run_scripted and args.codex_binary is None:
        runner = ScriptedRunner(lambda frozen: prompt_action(frozen['snapshot']['text'] + footer_holder[0]))
        version = 'scripted-in-process'
    else:
        runner = CodexRunner(str(Path(args.codex_binary).resolve()) if args.codex_binary and '/' in args.codex_binary else args.codex_binary or 'codex',
            workdir=Path.cwd(), env_allowlist=reg.get('env_allowlist', ['PATH','HOME']), stderr_path=output/'codex.stderr.log')
        version = runner.version(reg.get('codex_version'))
        if not args.dry_run_scripted:
            from harness_v6.codex_pin import require_official_pin
            require_official_pin(runner.binary, version, reg.get('codex_binary_sha256'))
        if not args.dry_run_scripted and version == 'fake-codex 1':
            raise ValueError('fake executable cannot produce results')
        if args.dry_run_scripted and version != 'fake-codex 1':
            raise ValueError('dry-run process boundary only supports tests/fake_codex.py')
    prefix = production_prefix(routing=routing, machine_groups=machines,
                           setup_transitions={} if synthetic else env.manifest['setups'],
                           min_runs={} if synthetic else dict(env.min_runs),
                           snapshot_format=reg['snapshot_format'], token_counter=counter)
    run = LiveRun(factory, runner, directory=output, prefix=prefix, source_sha256=fixture_hash,
        context_token_budget=reg.get('context_token_budget') or 1000000, request_overhead_tokens=reg.get('request_overhead_tokens') or 0,
        output_reserve_tokens=reg.get('output_reserve_tokens') or 0, token_counter=counter, config=config,
        model=reg.get('model') or 'scripted', model_config=reg.get('model_config'), budget=budget, checkpoint_completed=True, snapshot_format=reg['snapshot_format'],
        model_note=registration.LABEL if args.dry_run_scripted else '',
        drift_rule=DriftRule(**reg['drift_rule']) if reg.get('drift_rule') else None)
    if run.prefix != prefix:
        raise ValueError('production prefix changed after construction; requalify recording contract')
    # ScriptedRunner consumes only the same public prompt as the fake process.
    if isinstance(runner, ScriptedRunner):
        original = runner.run
        footer_holder = ['']
        def scripted(argv, prompt, *, timeout):
            footer_holder[0] = '\nCYCLE_FOOTER\n' + prompt.rsplit('\nCYCLE_FOOTER\n',1)[1]
            return original(argv, prompt, timeout=timeout)
        runner.run = scripted
    run.metrics.exclude_first_hours = reg['steady_state_window']['exclude_first_hours']
    run.metrics.cached_input_weight = reg['cached_input_weight']
    if args.resume:
        if manifest['fixture_hash'] != fixture_hash or manifest['codex_version'] != version:
            raise ValueError('resume fixture/version mismatch')
        run.recover()
    else:
        commit = subprocess.run(['git','rev-parse','HEAD'], capture_output=True, text=True, check=True).stdout.strip()
        manifest = dict(identity, fixture_hash=fixture_hash, registration=reg, codex_version=version,
            model=run.model, snapshot_format=reg['snapshot_format'], start=run.factory.now,
            registered_end=reg['end_time'], git_commit=commit,
            is_result=not args.dry_run_scripted, label=registration.LABEL if args.dry_run_scripted else '模型实验')
    atomic_write(manifest_path, canonical(manifest))
    run.checkpoint(run.store)
    session_limit = getattr(args, 'max_sessions', None)
    if session_limit is not None and session_limit < 1: raise ValueError('max_sessions must be positive')
    initial_sessions = run.cycle.sessions
    limited = False
    while run.factory.now < stop and not run.cycle.stop_reason:
        run.step(until=stop)
        values = totals(run)
        print(f"time={run.factory.now:.3f} cycles={run.cycle.cycles} sessions={run.cycle.sessions} tokens={values.get('input_tokens',0)}", flush=True)
        if run.cycle.last_record and run.cycle.last_record.get('segment_boundary'):
            cap = reg.get('per_sim_hour_request_cap')
            if cap is not None and values['model_request_lower_bound_per_sim_hour'] > cap:
                run.cycle.stop_reason = run.cycle.stop_reason or 'request_budget_cap'
        if session_limit is not None and run.cycle.sessions - initial_sessions >= session_limit:
            limited = True
            break
    # A requested endpoint is also a segment boundary for budget accounting.
    final_totals = totals(run)
    for metric, cap_key, stop_reason in (
        ('uncached_equivalent_input_tokens_per_sim_hour','per_sim_hour_token_cap','budget_cap'),
        ('model_request_lower_bound_per_sim_hour','per_sim_hour_request_cap','request_budget_cap')):
        cap = reg.get(cap_key)
        if cap is not None and final_totals.get(metric) is not None and final_totals[metric] > cap:
            run.cycle.stop_reason = run.cycle.stop_reason or stop_reason
    run.checkpoint(run.store)
    reason = run.cycle.stop_reason or ('session_limit' if limited else 'registered_end' if stop == reg['end_time'] else 'until')
    manifest.update(end=run.factory.now, stop_reason=reason)
    atomic_write(manifest_path, canonical(manifest))
    summary = dict(totals=totals(run), evaluation_totals=totals(run, steady_only=True), per_hour=run.metrics.report(), steady_state=run.metrics.report(steady_only=True),
        stop_reason=reason, budget_report=dict(context_failure=run.budget_report,
            per_sim_hour_token_cap=reg.get('per_sim_hour_token_cap'),
            per_sim_hour_request_cap=reg.get('per_sim_hour_request_cap'),
            observed={k:totals(run).get(k) for k in reg['primary_metrics']}), start=manifest['start'], end=run.factory.now,
        quality_basis='completed lots; tardiness weighted by lot.weight, default 1; CQT not implemented')
    atomic_write(output/'summary.json', canonical(summary))
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--registration',required=True); p.add_argument('--group',choices=['E1','P1','E2','P2'],required=True)
    p.add_argument('--trajectory',type=int,required=True); p.add_argument('--output',required=True)
    p.add_argument('--resume',action='store_true'); p.add_argument('--dry-run-scripted',action='store_true')
    p.add_argument('--max-sessions', type=int, help='stop after this many additional sessions (smoke test)')
    p.add_argument('--codex-binary'); p.add_argument('--until',type=float)
    execute(p.parse_args())

if __name__=='__main__': main()
