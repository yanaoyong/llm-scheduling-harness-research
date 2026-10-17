"""An external trace hash must bind what the metric passes actually consumed."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab import stream_metrics
from tests.test_smt_fullfab_metrics import metric_events


class MetricBindingTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'trace.jsonl'
        self.events=metric_events();self.write(self.events)
        self.expected=hashlib.sha256(self.path.read_bytes()).hexdigest()

    def write(self,events):
        self.path.write_text(''.join(json.dumps(e)+'\n\n' for e in events))

    def test_bound_metrics_preserve_exact_original_fields_and_types(self):
        unbound=stream_metrics.compute_metrics(self.path)
        bound=stream_metrics.compute_metrics(self.path,expected_source_sha256=self.expected)
        self.assertEqual(json.dumps(bound,sort_keys=True),json.dumps(unbound,sort_keys=True))

    def test_same_replacement_in_both_passes_cannot_borrow_previous_trace_hash(self):
        changed=deepcopy(self.events);changed[0]['manifest']['lots'][0]['due']-=123
        self.write(changed)
        stream_metrics.compute_metrics(self.path)  # self-consistent, but wrong source
        with self.assertRaisesRegex(ValueError,'externally expected'):
            stream_metrics.compute_metrics(self.path,expected_source_sha256=self.expected)

    def test_changed_second_pass_still_rejected_under_external_binding(self):
        original=stream_metrics._events;calls=0
        def replaced(path,hasher):
            nonlocal calls
            calls+=1
            if calls==2:
                changed=deepcopy(self.events);changed[0]['manifest']['lots'][0]['due']-=1
                self.write(changed)
            yield from original(path,hasher)
        with patch.object(stream_metrics,'_events',side_effect=replaced):
            with self.assertRaisesRegex(ValueError,'between streaming passes'):
                stream_metrics.compute_metrics(self.path,expected_source_sha256=self.expected)

    def test_raw_blank_lines_are_part_of_external_identity(self):
        self.path.write_text(self.path.read_text().replace('\n\n','\n'))
        with self.assertRaisesRegex(ValueError,'externally expected'):
            stream_metrics.compute_metrics(self.path,expected_source_sha256=self.expected)

    def test_invalid_expected_hash_rejected_before_read(self):
        self.path.unlink()
        for invalid in (True,1,'a'*63,'A'*64,'z'*64):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                stream_metrics.compute_metrics(self.path,expected_source_sha256=invalid)


if __name__=='__main__':unittest.main()
