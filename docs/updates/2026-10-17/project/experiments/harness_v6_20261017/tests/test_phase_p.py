"""All subprocesses here are explicitly fake; HTTP is loopback only."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from test_ab_comprehension import ab, states
from test_codex_runner import FAKE

SCRIPTS = Path(__file__).resolve().parents[1]/'scripts'

def module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS/(name+'.py'))
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


@pytest.mark.parametrize('url', ['https://api.openai.com/v1','http://localhost:80/v1','http://127.0.0.1.evil:90/v1','http://user@127.0.0.1:80/v1'])
def test_probe_refuses_non_loopback(url):
    with pytest.raises(ValueError, match='127.0.0.1'): module('run_codex_probes').provider_settings(url)


def test_probe_manifest_existing_consumers(tmp_path):
    probes = module('run_codex_probes')
    root = tmp_path/'probes'
    manifest = probes.run(str(FAKE), 'fake-codex 1', root)
    assert len(manifest['checks']) == 12 and manifest['mechanism_only']
    from probe_checks import check_f6, check_single_action, require_real_codex
    for check in manifest['checks']:
        validate = check_single_action if check.startswith('single_') else check_f6
        validate(root, manifest, check)
    with pytest.raises(AssertionError, match='mechanism-only'):
        require_real_codex(manifest)
    # Evidence changes invalidate evaluation; no unconditional success flags.
    endpoint, row = probes.capture(str(FAKE), 'fake-codex 1', tmp_path/'bad', 'config_injection', timeout=.001)
    assert not row['passed']


def test_ab_runner_fake_and_budget(tmp_path, monkeypatch):
    kit = tmp_path/'kit'; ab.generate(states(), kit, per_type=2)
    monkeypatch.setenv('FAKE_AB_ANSWERS', str(kit/'answer_key.json'))
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join(str(Path(p).resolve()) for p in sys.path))
    kw = dict(codex_binary=str(FAKE), codex_version='fake-codex 1', model='fake-only',
              context_token_budget=1000000, request_overhead_tokens=100,
              output_reserve_tokens=5000, counter=len,
              env_allowlist=['PATH','PYTHONPATH','FAKE_AB_ANSWERS'])
    manifest = ab.run(kit, tmp_path/'run', **kw)
    result = ab.score(kit/'questions.json', tmp_path/'run/answers', tmp_path/'score.json')
    assert all(r['overall']['accuracy'] == 1 for r in result['summary'].values())
    assert len(manifest['requests']) == 4
    assert all('model_max_output_tokens=5000' in r['command'] and 'model_auto_compact_token_limit=1000001' in r['command'] for r in manifest['requests'])
    assert all('mcp_servers={}' in r['command'] for r in manifest['requests'])
    kw['context_token_budget'] = 1
    with pytest.raises(ValueError, match='context budget'): ab.run(kit, tmp_path/'bad', **kw)
    assert not (tmp_path/'bad').exists()


def test_capture_overhead_real_recording_synthetic_snapshot(tmp_path):
    probes = module('run_codex_probes'); overhead = module('measure_request_overhead')
    snapshots = states()['synthetic']
    for mode in ('config_injection', 'single_schema_no_mcp'):
        logs = {}
        for fmt, snapshot in snapshots.items():
            root = tmp_path/(mode+fmt)
            _, row = probes.capture(str(FAKE), 'fake-codex 1', root, mode,
                prompt=snapshot.decode(), overhead_rounds=2)
            assert row['passed'], row
            logs[fmt] = [json.loads(line) for line in (root/'requests.jsonl').read_text().splitlines()]
        result = overhead.measure(logs, {k:v.decode() for k,v in snapshots.items()}, len,
                                  context_token_budget=10**7, output_reserve_tokens=1000)
        assert result['passed']
        expected = 3 if mode == 'config_injection' else 1
        assert result['formats']['dense']['request_count'] == expected
        if expected == 3:
            assert result['formats']['dense']['rounds'][-1]['growth_from_first_round'] > 0
            assert 'submit_plan' in json.dumps(logs['dense'][0])


def test_preflight_hashes_detect_tamper_and_escape(tmp_path):
    import hashlib
    preflight = module('mac_preflight')
    (tmp_path/'data').write_bytes(b'data')
    expected = dict(data={'data':hashlib.sha256(b'data').hexdigest()})
    assert all(r[1] for r in preflight.hashes(expected, dict(data=tmp_path)))
    (tmp_path/'data').write_bytes(b'changed')
    assert not preflight.hashes(expected, dict(data=tmp_path))[0][1]
    assert not preflight.hashes(dict(data={'../escape':'x'}), dict(data=tmp_path))[0][1]
    assert not preflight.hashes({}, dict(data=tmp_path))[0][1]


def test_one_session_smoke_limit_and_resume(tmp_path):
    from test_run_cli import registration, args
    cli = module('run_live'); reg = registration(tmp_path/'reg.json')
    first = args(reg, tmp_path/'smoke'); first.max_sessions = 1
    result = cli.execute(first)
    assert result['totals']['sessions'] == 1 and result['stop_reason'] == 'session_limit'
    continued = args(reg, tmp_path/'smoke', resume=True); continued.max_sessions = 1
    result = cli.execute(continued)
    assert result['totals']['sessions'] == 2


def test_ab_schema_types():
    assert not ab.schema_matches(True, {'type':'integer'})
    assert not ab.schema_matches(float('nan'), {'type':'number'})
    assert not ab.schema_matches({'x':'bad'}, ab.object_schema({'x':ab.NUMBER}))
    assert ab.schema_matches({'x':1}, ab.object_schema({'x':ab.NUMBER}))


def test_preflight_cli_version_only(tmp_path):
    manifest = tmp_path/'hashes.json'; manifest.write_text('{}')
    output = tmp_path/'preflight.json'
    argv = [sys.executable, str(SCRIPTS/'mac_preflight.py')]
    for option in ('physical-root','data-dir','vendor-dir','evidence-root'):
        argv += ['--'+option, str(tmp_path)]
    argv += ['--hash-manifest',str(manifest),'--codex-binary',str(FAKE),
             '--codex-version','fake-codex 1','--tiktoken-version','0.14.0','--output',str(output)]
    result = subprocess.run(argv, capture_output=True, text=True)
    assert result.returncode == 1  # deliberately absent inputs, not skipped
    report = json.loads(output.read_text())
    assert next(r for r in report['checks'] if r['name']=='Codex pin')['passed']
    assert report['authentication'].startswith('not tested')


@pytest.mark.parametrize('mechanism_only', [True, None, 0, 'false'])
def test_mac_gate_rejects_non_real_manifest(mechanism_only):
    from probe_checks import require_real_codex
    with pytest.raises(AssertionError, match='mechanism-only'):
        require_real_codex({'mechanism_only': mechanism_only})


def test_mac_gate_rejects_fake_binary_even_if_flag_changed(tmp_path):
    from probe_checks import require_real_codex
    alias = tmp_path/'codex'
    alias.symlink_to(FAKE)
    for binary in (FAKE, alias, Path('/archived/repository/tests/fake_codex.py')):
        manifest = dict(mechanism_only=False, codex_version='codex pinned',
                        checks={'probe': {'command': [str(binary)]}})
        with pytest.raises(AssertionError, match='repository fake'):
            require_real_codex(manifest)
