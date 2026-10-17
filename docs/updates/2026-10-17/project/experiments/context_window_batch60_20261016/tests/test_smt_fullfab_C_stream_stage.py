"""The unchanged 7 v3 full tiny attribution cases against installed modules."""
import unittest
from tests.test_smt_fullfab_C_stream_fixture_loader import load_fixture, export_tests

fixture = load_fixture('test_stream_stage.py', 'ab50f36e09a6500c20db293beffdae040843982e55c3b827a0422603be2e292b',
    '_C8_v3_stream_stage_tests', module_name='_installed_C8_stage_fixture')
export_tests(fixture, globals())

if __name__ == '__main__':
    unittest.main()
