"""Wire-level action order and evidence binding, with no remote inference."""
import unittest
from src.smt_fullfab.harness.contracts import encode, encode_model_schema, sha_bytes, strict_json
from src.smt_fullfab.harness.transport import response_schema
from src.smt_fullfab.harness.evaluation import seal_evidence, audit_run
from tests import test_smt_fullfab_harness_bounded_recovery as fixtures


class SchemaOrderTests(unittest.TestCase):
    def test_T06_all_wire_branches_choose_tool_before_arguments(self):
        for arm in ('B', 'C'):
            for refs, opened in (([], False), (['candidate:old', 'candidate:new'], False), (['candidate:old'], True)):
                schema = response_schema(arm, comparison_context_refs=['context:prior'], candidate_refs=refs, has_open_draft=opened)
                raw = encode_model_schema(schema)
                wire = strict_json(raw)
                self.assertEqual(wire, schema)
                for branch in wire['properties']['action']['anyOf']:
                    self.assertEqual(next(iter(branch['properties'])), 'tool')
                    self.assertEqual(branch['required'][0], 'tool')
                # Reproduce the actual previous defect rather than merely
                # testing the in-memory schema builder.
                old = strict_json(encode(schema))
                self.assertTrue(all(next(iter(a['properties'])) != 'tool' for a in old['properties']['action']['anyOf']))
                self.assertNotEqual(raw, encode(schema))

    def test_T15_T16_actual_transport_and_guard_bind_ordered_schema_bytes(self):
        helper = fixtures.BoundedRecoveryTests(); helper.setUp(); self.addCleanup(helper.doCleanups)
        runtime = helper.new()
        result = helper.invoke(runtime, action={'tool':'write_notes', 'context_ref':runtime.head['context_ref'],
                                               'request_id':'wire-test', 'text':'offline', 'expected_version':0})
        self.assertEqual(result['status'], 'ok')
        attempt = runtime.store.rows('attempts')[0][1]
        directory = runtime.store.path/'model'/attempt['attempt_id'].replace(':','-')
        raw = (directory/'schema.json').read_bytes()
        self.assertEqual(sha_bytes(raw), attempt['schema_ref'])
        self.assertEqual(runtime.store.bytes(attempt['schema_ref']), raw)
        for branch in strict_json(raw)['properties']['action']['anyOf']:
            self.assertEqual(next(iter(branch['properties'])), 'tool')
        spec = strict_json((directory/'process_guard/spec.json').read_bytes())
        self.assertEqual(spec['input_files_sha256']['schema.json'], sha_bytes(raw))
        runtime.stop('offline_schema_byte_test')
        boundary = seal_evidence(runtime)
        audit = audit_run(runtime.store.path, expected_sha256=boundary)
        self.assertTrue(audit['cost_accounting']['valid'], audit['cost_accounting'])


if __name__ == '__main__': unittest.main()
