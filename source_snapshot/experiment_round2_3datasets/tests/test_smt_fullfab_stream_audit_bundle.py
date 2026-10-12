"""Tiny independent saved-event integration; no factory/model/solver calls."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab.audit import audit_trace
from tests.test_smt_fullfab_audit import trace_fixture,renumber

spec=importlib.util.spec_from_file_location('draft_audit_bundle',Path(__file__).resolve().parents[1] / 'src/smt_fullfab/stream_audit_bundle.py')
candidate=importlib.util.module_from_spec(spec);spec.loader.exec_module(candidate)


class AuditBundleTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name).resolve();self.source=self.root/'trace.jsonl'
        self.out=self.root/'bundle';self.events=trace_fixture();self.write(self.events)

    def write(self,events):
        self.source.write_text(''.join(json.dumps(e)+'\n\n' for e in events))
        self.expected=candidate.sha_file(self.source)

    def run_audit(self,**kw):
        return candidate.audit_to_bundle(self.source,output_dir=self.out,
            expected_source_sha256=self.expected,**kw)

    def test_valid_complete_components_match_legacy_and_survive_storage_recheck(self):
        legacy=audit_trace(self.events);result=self.run_audit()
        self.assertTrue(result['summary']['valid'])
        self.assertTrue(result['summary']['complete_physical_window_certified'])
        self.assertTrue(result['summary']['absence_of_unreported_legal_demand_certified'])
        for name,key,subkey in [('source.json','plan_source_audit',None),
                ('opportunity.json','opportunity_audit',None),('physical.json','physical_replay','physical_report'),
                ('metrics.json','metrics','metrics')]:
            actual=json.loads((self.out/name).read_text());actual=actual[subkey] if subkey else actual
            expected=deepcopy(legacy[key])
            for item in ('audit_version','_core_scope','_source_evidence'):actual.pop(item,None);expected.pop(item,None)
            if key=='plan_source_audit':
                # Standalone provenance correctly refuses to certify other checks.
                self.assertFalse(actual.pop('absence_of_unreported_legal_demand_certified'))
                expected.pop('absence_of_unreported_legal_demand_certified');actual.pop('scope');expected.pop('scope')
            self.assertEqual(json.dumps(actual,sort_keys=True),json.dumps(expected,sort_keys=True),name)
        again=candidate.read_bundle(self.out,expected_manifest_sha256=result['report_sha256'])
        self.assertTrue(again['storage_verified']);self.assertFalse(again['semantic_replay_performed'])
        self.assertEqual(again['summary'],result['summary'])

    def test_semantically_wrong_dispatch_keeps_complete_failure_evidence(self):
        self.events[4]['plan_version']='missing';self.write(self.events)
        result=self.run_audit()
        self.assertFalse(result['summary']['valid']);self.assertFalse(result['summary']['complete_physical_window_certified'])
        self.assertTrue((self.out/'physical.json').exists())
        self.assertTrue(candidate.read_bundle(self.out,expected_manifest_sha256=result['report_sha256'])['storage_verified'])

    def test_source_hash_required_and_wrong_hash_never_publish_completion(self):
        with self.assertRaises(ValueError):candidate.audit_to_bundle(self.source,output_dir=self.out,expected_source_sha256=None)
        self.assertFalse(self.out.exists())
        self.expected='0'*64
        with self.assertRaises(ValueError):self.run_audit()
        self.assertFalse((self.out/candidate.MANIFEST).exists())

    def test_nonterminal_requires_explicit_prefix_mode_and_never_certifies_window(self):
        self.write(self.events[:-1])
        with self.assertRaises(ValueError):self.run_audit()
        self.assertFalse((self.out/candidate.MANIFEST).exists())
        self.out=self.root/'prefix'
        result=self.run_audit(require_terminal=False)
        self.assertFalse(result['summary']['complete_physical_window_certified'])

    def test_foreign_component_receipt_prevents_complete_manifest(self):
        original=candidate.stream_source_audit.audit_plan_sources
        def wrong(*a,**kw):
            out=original(*a,**kw);out['source_receipt']['sha256']='1'*64;return out
        with patch.object(candidate.stream_source_audit,'audit_plan_sources',side_effect=wrong):
            with self.assertRaises(ValueError):self.run_audit()
        self.assertFalse((self.out/candidate.MANIFEST).exists())

    def test_metric_error_preserves_intermediates_without_complete_manifest(self):
        with patch.object(candidate.stream_metrics,'compute_metrics',side_effect=ValueError('synthetic metric error')):
            with self.assertRaisesRegex(ValueError,'synthetic'):self.run_audit()
        self.assertTrue((self.out/'physical.json').exists())
        self.assertFalse((self.out/candidate.MANIFEST).exists())

    def test_source_replacement_after_metrics_prevents_publication(self):
        original=candidate.stream_metrics.compute_metrics
        def changed(*a,**kw):
            result=original(*a,**kw)
            self.source.write_bytes(self.source.read_bytes()+b'\n')
            return result
        with patch.object(candidate.stream_metrics,'compute_metrics',side_effect=changed):
            with self.assertRaises(ValueError):self.run_audit()
        self.assertFalse((self.out/candidate.MANIFEST).exists())

    def test_existing_bundle_not_reused_even_if_empty(self):
        self.out.mkdir()
        with self.assertRaises(FileExistsError):self.run_audit()

    def test_changed_report_fails_storage_recheck(self):
        result=self.run_audit();p=self.out/'source.json';p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaises(ValueError):candidate.read_bundle(self.out,expected_manifest_sha256=result['report_sha256'])

    def test_changed_manifest_and_foreign_external_sha_rejected(self):
        result=self.run_audit()
        with self.assertRaises(ValueError):candidate.read_bundle(self.out,expected_manifest_sha256='0'*64)
        p=self.out/candidate.MANIFEST;p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaises(ValueError):candidate.read_bundle(self.out,expected_manifest_sha256=result['report_sha256'])

    def test_member_symlink_rejected_even_with_same_bytes(self):
        result=self.run_audit();p=self.out/'source.json';backup=self.root/'same.json'
        p.rename(backup);p.symlink_to(backup)
        with self.assertRaises(ValueError):candidate.read_bundle(self.out,expected_manifest_sha256=result['report_sha256'])

    def test_truncated_suffix_and_invalid_snapshot_never_publish_manifest(self):
        self.source.write_bytes(self.source.read_bytes()+b'{');self.expected=candidate.sha_file(self.source)
        with self.assertRaises(ValueError):self.run_audit()
        self.assertFalse((self.out/candidate.MANIFEST).exists())
        self.out=self.root/'badprefix'
        es=self.events[:-1]+[{'kind':'snapshot_loaded','time':20,'prefix_event_count':0,'snapshot_sha256':'a'*64}]+self.events[-1:]
        self.write(renumber(es))
        with self.assertRaises(ValueError):self.run_audit()
        self.assertFalse((self.out/candidate.MANIFEST).exists())


if __name__=='__main__':unittest.main()
