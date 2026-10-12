"""Installation-only source/snapshot checks with a tiny synthetic source root."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab import C_stream_controller as controller
from src.smt_fullfab import C_stream_attribution_stage as stage
from src.smt_fullfab import runner, model_transport_supervised

ROOT = Path(__file__).resolve().parents[1]
DRAFT = ROOT / 'artifacts/smt_fullfab_review_drafts/C8_stream_controller_v3'
INSTALLED = ROOT / 'src/smt_fullfab'


class InstallationTests(unittest.TestCase):
    def test_controller_has_only_registered_supervision_and_authority_diff(self):
        record = json.loads((ROOT / 'artifacts/smt_fullfab_diagnostics/C8_installation_v3/change_record.json').read_text())
        self.assertEqual(hashlib.sha256((INSTALLED / 'C_stream_controller.py').read_bytes()).hexdigest(), record['controller_sha256'])
        self.assertIs(controller.call_model, model_transport_supervised.call_model)
        self.assertIs(controller.ModelConfig, model_transport_supervised.ModelConfig)
        self.assertEqual(controller.VERSION, 'fullfab-C8-stream-controller-v4-supervised')
        with self.assertRaisesRegex(RuntimeError, 'external frozen C_stream_gate'):
            controller.run()
        self.assertEqual((INSTALLED / 'C_plan_archive.py').read_bytes(), (DRAFT / 'plan_archive.py').read_bytes())
        self.assertEqual(controller.PROPOSAL['max_log_bytes'], 24 * 1024 ** 3)
        self.assertEqual(controller.PROPOSAL['minimum_free_bytes'], 64 * 1024 ** 3)
        self.assertIsNone(controller.PROPOSAL['max_calls'])
        self.assertIsNone(controller.PROPOSAL['max_tokens'])

    def test_fixed_dependencies_and_installed_path_are_exact(self):
        expected_dir = Path(stage.__file__).resolve().with_name('C_stream_attribution_v2')
        self.assertEqual(stage.DEFAULT_ATTRIBUTION_SOURCE_DIR, expected_dir)
        self.assertEqual(stage.DEFAULT_CONSTRUCTOR_SOURCE, expected_dir / 'constructor_stream.py')
        for name, expected in stage.ATTRIBUTION_SOURCES.items():
            raw = (expected_dir / name).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), expected)
            self.assertEqual(raw, (DRAFT.parent / 'C8_stream_attribution_v2' / name).read_bytes())
        raw = stage.DEFAULT_CONSTRUCTOR_SOURCE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), stage.CONSTRUCTOR_SHA256)
        self.assertEqual(raw, (DRAFT.parent / 'C8_constructor_stream_v1/constructor_stream.py').read_bytes())

    def test_flat_snapshot_and_explicit_dependency_keys_are_all_recoverable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_source = root / 'synthetic-frozen-source'
            out = root / 'synthetic-run'
            out.mkdir()
            for base in ('src/smt_fullfab', 'src/smt'):
                (fake_source / base).mkdir(parents=True)
            for name in ('C_stream_controller.py', 'C_plan_archive.py', 'C_stream_attribution_stage.py'):
                (fake_source / 'src/smt_fullfab' / name).write_bytes((INSTALLED / name).read_bytes())
            (fake_source / 'src/smt/tiny.py').write_text('# inert source only\n')
            (fake_source / 'src/__init__.py').write_text('')
            (fake_source / 'requirements.lock').write_text('# inert lock fixture\n')
            with patch.object(runner, 'ROOT', fake_source), \
                    patch.object(runner.subprocess, 'check_output', return_value='synthetic-git-pointer\n'):
                provenance = runner.source_snapshot(out)
            bound = stage.validate_sources(stage.DEFAULT_ATTRIBUTION_SOURCE_DIR, stage.ATTRIBUTION_SOURCES,
                constructor_source=stage.DEFAULT_CONSTRUCTOR_SOURCE,
                expected_constructor_sha256=stage.CONSTRUCTOR_SHA256)
            destination, inventory = stage.snapshot_sources(out, bound)
            provenance['source_sha256'].update(inventory)
            (out / 'provenance.json').write_text(json.dumps(provenance))
            expected_keys = {'src/smt_fullfab/' + name for name in
                ('C_stream_controller.py', 'C_plan_archive.py', 'C_stream_attribution_stage.py')}
            expected_keys.update('attribution_stream_v2/' + name for name in
                ('audit_candidate.py', 'legacy_checks.py', 'storage.py', 'constructor_stream.py'))
            self.assertLessEqual(expected_keys, provenance['source_sha256'].keys())
            self.assertEqual(destination, out / 'source_snapshot/attribution_stream_v2')
            for relative, expected in provenance['source_sha256'].items():
                self.assertEqual(hashlib.sha256((out / 'source_snapshot' / relative).read_bytes()).hexdigest(), expected)


if __name__ == '__main__':
    unittest.main()
