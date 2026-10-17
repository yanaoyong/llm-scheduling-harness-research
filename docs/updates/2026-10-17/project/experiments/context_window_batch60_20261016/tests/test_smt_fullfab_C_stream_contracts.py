"""The unchanged 39 v3 contract cases against installed production modules."""
import unittest
from tests.test_smt_fullfab_C_stream_fixture_loader import load_fixture, export_tests

fixture = load_fixture('test_contracts.py', '1632e6be5b9d8fa703daed15acd2f655a8a03e7a2dc36d9a756734b47a90d427',
    '_isolated_C8_v3_contract_tests', module_name='_installed_C8_contract_fixture')
export_tests(fixture, globals())

if __name__ == '__main__':
    unittest.main()
