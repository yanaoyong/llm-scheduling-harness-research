"""Offline process boundary proofs. No real Codex or model is invoked."""
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import sys
import time
import pytest
from harness_v6.codex_runner import CodexRunner
from harness_v6.synthetic import SyntheticRun
from harness_v6.live import LiveRun
from harness_v6.session import Budget, classify
from harness_v6.evidence import audit_provenance
from harness_v6.prompt_rules import cycle_footer

FAKE = Path(__file__).with_name('fake_codex.py').resolve()


def runner(tmp_path, monkeypatch, mode=''):
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join(str(Path(p).resolve()) for p in sys.path))
    monkeypatch.setenv('FAKE_CODEX_MODE', mode)
    return CodexRunner(FAKE, workdir=tmp_path,
        env_allowlist=['PATH','HOME','PYTHONPATH','FAKE_CODEX_MODE','FAKE_CHILD_PID'], stderr_path=tmp_path/'stderr.log')


@pytest.mark.parametrize('group',['E1','P1','E2','P2'])
def test_process_ten_decisions(group,tmp_path,monkeypatch):
    run=SyntheticRun(group=group,directory=tmp_path/'run')
    run.runner=runner(tmp_path,monkeypatch)
    assert run.runner.version('fake-codex 1') == 'fake-codex 1'
    for i in range(10):
        LiveRun.step(run)
        assert run.outcome['adopted'],run.outcome
        directory=run.directory/f'cycle-{i+1}'
        parsed=classify((directory/'output/session.jsonl').read_text(),interaction=run.cycle.config.interaction)
        assert not parsed['errors']
        if group.endswith('2'):
            rows=[json.loads(s) for s in (directory/'output/mcp.jsonl').read_text().splitlines()]
            assert not audit_provenance(rows,parsed['calls'],json.loads((directory/'output/submission.json').read_text()),json.loads((directory/'initial.json').read_text()))
    assert sum(r['model_request_lower_bound'] for r in run.metrics.buckets.values()) == (30 if group.endswith('2') else 10)
    assert 'fake codex stderr' in (tmp_path/'stderr.log').read_text()


@pytest.mark.parametrize('mode',['forbidden','nonzero','malformed','missing_usage','crash_after_submit','hang'])
def test_failed_process_retains_plan_and_stops(mode,tmp_path,monkeypatch):
    run=SyntheticRun(directory=tmp_path/'run');run.step()
    old=deepcopy(run.factory.plan)
    run.runner=runner(tmp_path,monkeypatch,mode)
    run.budget=Budget(wall_seconds=.2 if mode=='hang' else 10)
    for _ in range(2):
        LiveRun.step(run)
        assert not run.outcome['adopted'] and run.factory.plan==old
    assert run.cycle.stop_reason in ('consecutive_failures','unknown_usage_cap')


def test_timeout_group_and_version(tmp_path,monkeypatch):
    monkeypatch.setenv('FAKE_CHILD_PID',str(tmp_path/'child'))
    r=runner(tmp_path,monkeypatch,'hang')
    result=r.run(['codex','exec','-'],'',timeout=.3)
    assert result.timed_out and result.returncode != 0 and result.wall_seconds >= .3
    pid=int((tmp_path/'child').read_text())
    # On Linux an orphan zombie may briefly await PID 1 reaping; it is not running.
    stat=Path(f'/proc/{pid}/stat')
    assert not stat.exists() or stat.read_text().split()[2]=='Z'
    with pytest.raises(ValueError,match='mismatch'): r.version('other')
    assert 'UNREGISTERED_SECRET' not in r.env


def test_footer_deterministic():
    args=dict(state_version=1,submission_id='1',now=0,next_anchor=60,delta=60,delta_min=60,
              trigger='periodic',interaction='mcp_session',wall_seconds=300)
    assert cycle_footer(**args)==cycle_footer(**args)
    assert json.loads(cycle_footer(**args).split('CYCLE_FOOTER\n')[1])['valid_until_minimum']==120
    args.update(trigger='event',next_anchor=None)
    assert json.loads(cycle_footer(**args).split('CYCLE_FOOTER\n')[1])['valid_until_minimum']==60


def test_prompt_prefix_current_footer_and_budget(tmp_path):
    run=SyntheticRun(directory=tmp_path/'run')
    seen=[];original=run.runner.run
    def record(argv,prompt,**kw):
        seen.append(prompt);return original(argv,prompt,**kw)
    run.runner.run=record
    for _ in range(2): run.step()
    from harness_v6.snapshot import decode_snapshot
    for index,prompt in enumerate(seen,1):
        snapshot,footer=prompt.rsplit('\nCYCLE_FOOTER\n',1)
        assert prompt.startswith(run.prefix.decode())
        state=decode_snapshot(snapshot.encode())[1]
        assert state['state_version']==index
        assert json.loads(footer)['expected_state_version']==index
        assert json.loads(footer)['submission_id']==str(index)
    # Snapshot alone fits, but adding the instruction tail must prevent launch.
    limited=SyntheticRun(directory=tmp_path/'limited')
    limited.token_counter=len
    limited.context_token_budget=len(seen[0].rsplit('\nCYCLE_FOOTER\n',1)[0])+1
    limited.step()
    assert limited.cycle.stop_reason=='context_budget_exceeded'
    assert not list(limited.directory.glob('cycle-*'))


def test_fake_planner_keeps_retained_future_bounds_inside_validity(tmp_path):
    from harness_v6.synthetic import prompt_action
    from harness_v6.snapshot import build_snapshot, estimate_tokens
    run=SyntheticRun(directory=tmp_path);run.step()
    run.factory.plan['tasks'][0]['not_before']=500
    snapshot=build_snapshot(run.prefix,run.factory.ledger(),state_version=2,running_jobs=[],
        last_cycle_receipt=None,model_notes='',token_budget=100000,token_counter=estimate_tokens)
    footer=cycle_footer(state_version=2,submission_id='2',now=0,next_anchor=60,delta=60,
        delta_min=60,trigger='periodic',interaction='mcp_session',wall_seconds=300)
    action=prompt_action(snapshot.decode()+footer)
    assert action['delta']['plan_header']['valid_until']>500
    assert not action['delta']['tasks']['replace']
