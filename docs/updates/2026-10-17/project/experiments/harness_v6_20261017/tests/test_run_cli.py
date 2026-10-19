import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import pytest
from test_codex_runner import FAKE

ROOT=Path(__file__).resolve().parents[1]


def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod


def registration(path, fixture='synthetic'):
    reg=json.loads((ROOT/'registration_template.json').read_text())
    reg.update(fixture=fixture, end_time=240 if fixture=='synthetic' else 882,
               context_token_budget=1000000, model='fake', codex_version='fake-codex 1',
               env_allowlist=['PATH','HOME','PYTHONPATH','TIKTOKEN_CACHE_DIR'],trajectory_seeds=[7,7,7])
    path.write_text(json.dumps(reg));return path


def args(reg,output,**kw):
    return argparse.Namespace(registration=str(reg),group='P2',trajectory=1,output=str(output),
        resume=kw.get('resume',False),dry_run_scripted=True,codex_binary=kw.get('binary'),until=kw.get('until'))


def test_cli_scripted_resume_summary(tmp_path):
    cli=module('run_live'); reg=registration(tmp_path/'reg.json')
    first=tmp_path/'first';second=tmp_path/'second'
    cli.execute(args(reg,first,until=120))
    cli.execute(args(reg,first,resume=True))
    other=args(reg,second);other.trajectory=2;cli.execute(other)
    assert json.loads((first/'summary.json').read_text())['totals']['throughput']>0
    result=module('summarize_runs').summarize([first,second],tmp_path/'summary')
    assert result['dry_run'] and not result['is_result']
    with pytest.raises(ValueError,match='mismatch'):
        bad=args(reg,first,resume=True);bad.trajectory=2;cli.execute(bad)
    manifest=json.loads((second/'run_manifest.json').read_text());manifest['dry_run']=False
    (second/'run_manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='dry_run'):module('summarize_runs').summarize([first,second],tmp_path/'bad')


def test_configured_cli_fake_crash_resume(tmp_path,monkeypatch):
    from mac_fixture import bundle
    bundle('mixed_702')
    monkeypatch.setenv('PYTHONPATH',os.pathsep.join(str(Path(p).resolve()) for p in sys.path))
    cli=module('run_live');reg=registration(tmp_path/'reg.json',os.environ['V6_MAC_FIXTURE'])
    original=cli.CodexRunner.run
    calls=[0]
    def crash(self,*a,**kw):
        result=original(self,*a,**kw);calls[0]+=1
        if calls[0]==2: raise RuntimeError('injected host crash')
        return result
    monkeypatch.setattr(cli.CodexRunner,'run',crash)
    with pytest.raises(RuntimeError,match='injected'):
        cli.execute(args(reg,tmp_path/'one',binary=str(FAKE)))
    monkeypatch.setattr(cli.CodexRunner,'run',original)
    result=cli.execute(args(reg,tmp_path/'one',binary=str(FAKE),resume=True))
    assert result['end']==882 and result['totals']['sessions']>=3
    assert result['totals']['failures']==1
    two=args(reg,tmp_path/'two',binary=str(FAKE));two.trajectory=2
    result2=cli.execute(two)
    assert result2['totals']['sessions']>=3 and result2['totals']['failures']==0
    module('summarize_runs').summarize([tmp_path/'one',tmp_path/'two'],tmp_path/'summary')


def test_results_registration_requires_runner_fields(tmp_path):
    from harness_v6.registration import validate
    reg=json.loads(registration(tmp_path/'reg.json').read_text())
    reg.update(dry_run=False,plan_source='model',is_result=True,per_sim_hour_token_cap=1000,per_sim_hour_request_cap=10)
    for value in reg['quality'].values(): value.update(floor=0,tolerance=1)
    for key in ('codex_version','codex_binary_sha256','model','context_token_budget','request_overhead_tokens','output_reserve_tokens'):
        copy=dict(reg);copy[key]=None
        assert key in validate(copy,results=True)


def test_production_rejects_wrong_codex_pin(tmp_path):
    from harness_v6.codex_pin import require_official_pin, OFFICIAL_VERSION
    import hashlib
    binary=tmp_path/'codex';binary.write_bytes(b'fixture')
    sha=hashlib.sha256(binary.read_bytes()).hexdigest()
    assert require_official_pin(binary,OFFICIAL_VERSION,sha)==sha
    with pytest.raises(ValueError,match='official'):
        require_official_pin(binary,'codex-cli 0.147.0',sha)
    with pytest.raises(ValueError,match='official'):
        require_official_pin(binary,'codex-cli 0.163.0-harness-v6.5',sha)
    with pytest.raises(ValueError,match='sha256'):
        require_official_pin(binary,OFFICIAL_VERSION,'0'*64)


@pytest.mark.parametrize('group', ['E1', 'P2'])
def test_live_uses_context_and_output_limits_independently_of_cumulative_cap(tmp_path, group):
    cli=module('run_live'); reg_path=registration(tmp_path/'reg.json')
    reg=json.loads(reg_path.read_text())
    reg.update(context_token_budget=800000,output_reserve_tokens=4000)
    reg['session_budget']['token_cap']=12000000
    reg_path.write_text(json.dumps(reg))
    a=args(reg_path,tmp_path/'run');a.group=group;a.max_sessions=1
    cli.execute(a)
    argv=json.loads(next((tmp_path/'run').glob('cycle-*/output/command.json')).read_text())
    assert not any(x.startswith('model_max_output_tokens=') for x in argv)
    assert 'model_context_window=800000' in argv
    assert 'model_auto_compact_token_limit=800001' in argv
    assert 'tool_output_token_limit=800000' in argv
    assert not any(x.endswith('=12000000') for x in argv)


def test_physical_production_metrics_from_new_events_only():
    from harness_v6.factory_v6 import LiveFactory
    from harness_v6.metrics import Metrics
    class Env:
        t=10
        trace=[dict(kind='lot_complete',time=9,lot='old')]
        lots={'new':dict(due=11,weight=3)}
        def advance_cycle(self,*a,**kw):
            self.t=15;self.trace.append(dict(kind='lot_complete',time=15,lot='new'))
            return dict(reason='periodic_replan')
    factory=LiveFactory(Env());factory.metrics=Metrics(origin=10)
    factory.advance_to(15,False)
    assert factory.metrics.report()[0]['throughput']==1
    assert factory.metrics.report()[0]['weighted_tardiness']==12


def test_summary_comparison_and_quality(tmp_path):
    from copy import deepcopy
    reg=json.loads(registration(tmp_path/'reg.json').read_text())
    reg['trajectories_per_group']=1
    for rule in reg['quality'].values(): rule.update(floor=10,tolerance=2)
    paths=[]
    for group,cost in [('E1',100),('P2',50)]:
        path=tmp_path/group;path.mkdir();paths.append(path)
        manifest=dict(registration_hash='same',registration=reg,dry_run=True,start=0,registered_end=240,
            fixture_hash='same',codex_version='fake-codex 1',model='fake',snapshot_format='explicit',group=group,trajectory=1)
        values=dict(weighted_tardiness=5,throughput=10,avoidable_idle_seconds=4,explicit_wait_idle_seconds=0,
            failures=0,unknown_usage=0,uncached_equivalent_input_tokens_per_sim_hour=cost,model_request_lower_bound_per_sim_hour=cost)
        (path/'run_manifest.json').write_text(json.dumps(manifest))
        (path/'summary.json').write_text(json.dumps(dict(totals=values,stop_reason='registered_end',end=240,steady_state={})))
    result=module('summarize_runs').summarize(paths,tmp_path/'out')
    assert result['comparison']['quality_floors_held']
    assert all(result['comparison']['quality_vs_E1'].values())
    assert result['comparison']['model_request_lower_bound_per_sim_hour']
    assert 'P2 的请求数下界低于 E1' in (tmp_path/'out/results.md').read_text()
