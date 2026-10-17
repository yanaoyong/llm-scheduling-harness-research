"""Offline restoration subprocess bounds and durable timeout reporting."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab import recovery_check


class RestorationTimeoutTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve();self.run=self.root/'runs'/'synthetic'
        source=self.run/'source_snapshot'/'src'/'fixture.py'
        source.parent.mkdir(parents=True);source.write_text('# never executed\n')
        (self.run/'provenance.json').write_text(json.dumps({'source_sha256':{
            'src/fixture.py':hashlib.sha256(source.read_bytes()).hexdigest()}}))
        (self.run/'checkpoint.json').write_text(json.dumps({'state':{},'implementation_sha256':{}}))
        p=patch.object(recovery_check,'ROOT',self.root);p.start();self.addCleanup(p.stop)

    def test_default_remains_thirty_seconds(self):
        with patch.object(recovery_check.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'{"valid":true}','')) as run:
            result=recovery_check.verify(self.run)
        self.assertTrue(result['valid']);self.assertEqual(run.call_args.kwargs['timeout'],30)
        self.assertEqual(result['subprocess_timeout_seconds'],30)

    def test_explicit_timeout_recorded_and_passed_without_retry(self):
        with patch.object(recovery_check.subprocess,'run',side_effect=subprocess.TimeoutExpired('synthetic',120)) as run:
            result=recovery_check.verify(self.run,timeout_seconds=120)
        self.assertEqual(run.call_count,1);self.assertEqual(run.call_args.kwargs['timeout'],120)
        self.assertFalse(result['valid']);self.assertTrue(result['timed_out'])
        self.assertEqual(result['subprocess_timeout_seconds'],120)
        self.assertEqual(result['checkpoint_sha256'],recovery_check.sha(self.run/'checkpoint.json'))
        self.assertEqual(result['model_calls'],0);self.assertEqual(result['solver_calls'],0)
        self.assertGreaterEqual(result['wall_seconds'],0)

    def test_invalid_bounds_rejected_before_subprocess_or_source_read(self):
        with patch.object(recovery_check.subprocess,'run') as run:
            for value in (True,False,None,'120',0,0.5,181,float('inf'),float('nan')):
                with self.subTest(value=value),self.assertRaises(ValueError):
                    recovery_check.verify(self.root/'does-not-exist',timeout_seconds=value)
        run.assert_not_called()

    def test_nonzero_child_still_fails_without_retry(self):
        with patch.object(recovery_check.subprocess,'run',return_value=subprocess.CompletedProcess([],2,'','original error')) as run:
            result=recovery_check.verify(self.run,timeout_seconds=120)
        self.assertFalse(result['valid']);self.assertEqual(result['error'],'original error')
        self.assertEqual(result['returncode'],2);self.assertEqual(run.call_count,1)

    def test_source_mismatch_still_prevents_child(self):
        (self.run/'source_snapshot'/'src'/'fixture.py').write_text('# changed\n')
        with patch.object(recovery_check.subprocess,'run') as run:
            result=recovery_check.verify(self.run,timeout_seconds=120)
        self.assertFalse(result['valid']);self.assertIn('src/fixture.py',result['mismatches'])
        run.assert_not_called()


if __name__=='__main__':unittest.main()
