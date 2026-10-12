"""The unchanged 6 complete private v3 mock flows against installed modules."""
import unittest
from tests.test_smt_fullfab_C_stream_fixture_loader import load_fixture, export_tests

fixture = load_fixture('test_private_wire.py', '3bd16a3a6d345ebf890693647266fc0beae72d2e021281a4976cf7a709268b5e',
    '_C8_v3_private_wire_tests', module_name='_installed_C8_private_fixture')
export_tests(fixture, globals())

if __name__ == '__main__':
    unittest.main()
