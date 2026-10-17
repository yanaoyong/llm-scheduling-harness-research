"""A network repair cannot reset costs, replace prior runs or change physics."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab.harness.contracts import ROOT, HarnessError, digest, encode, fingerprint, sha_bytes, strict_json
from src.smt_fullfab.harness.experiment import checked_file
from src.smt_fullfab.harness.B_network_restart import MODEL, carried_costs, carried_recovery_count, validate_registration
from src.smt_fullfab.harness.diagnostic_costs import verify_chain, verify_attempt
from src.smt_fullfab.harness.network import apply_environment, validate_binding


class NetworkRestartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='offline-TUN-B-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.reg = strict_json((ROOT / 'artifacts/harness_astra_TUN_B_transition/registration_draft.json').read_bytes())
        original = Path(self.reg['experiment_directory'])
        self.usage = deepcopy(self.reg['carried_usage_at_registration'])
        self.reg['experiment_directory'] = str(self.root)
        self.grant = checked_file(self.reg['authorization'])
        self.grant['experiment_directory'] = str(self.root)
        self.cfg = strict_json((original / 'B3600.config.json').read_bytes())
        self.gate = checked_file(self.reg['entry_gate'])
        # This fixture validates the historical TUN registration, not a later
        # separately authorized control amendment.
        self.fp = strict_json((ROOT / 'artifacts/harness_astra_TUN_B_transition/engineering_acceptance.json').read_bytes())['fingerprint']
        proof = self.root / 'test-evidence.json'
        proof.write_bytes(encode({'all_pass': True, 'source_unchanged': True, 'remote_model_calls': 0, 'fingerprint_sha256': self.fp['sha256']}))
        self.report = {'fingerprint': self.fp, 'fingerprint_sha256': self.fp['sha256'],
                       'gates': {key: 'pass' for key in ('G0','G1','G2','G3','G4')}, 'test_evidence': self.ref(proof)}
        self.reg['fingerprint_sha256'] = self.fp['sha256']
        self.sync()

    def ref(self, path):
        return {'path': str(path), 'sha256': sha_bytes(path.read_bytes())}

    def sync(self):
        for name, value in (('authorization.json', self.grant), ('B3600.config.json', self.cfg), ('micro_gate.json', self.gate), ('engineering.json', self.report)):
            (self.root / name).write_bytes(encode(value))
        self.reg.update(authorization=self.ref(self.root / 'authorization.json'), entry_gate=self.ref(self.root / 'micro_gate.json'),
                        engineering_report=str(self.root / 'engineering.json'), engineering_report_sha256=self.ref(self.root / 'engineering.json')['sha256'])

    def validate(self):
        with patch('src.smt_fullfab.harness.B_network_restart.carried_costs', return_value=(self.usage, 2, {'prior'})), \
             patch('src.smt_fullfab.harness.B_network_restart.carried_recovery_count', return_value=14):
            return validate_registration(self.reg, self.root)

    def test_T20_exact_Astra_B_registration_and_model(self):
        self.assertEqual(self.validate(), self.reg)
        self.reg['model'] = {'name': 'gpt-6.1-astra', 'reasoning_effort': 'medium'}
        with self.assertRaisesRegex(HarnessError, 'B_restart_registration'): self.validate()

    def test_T20_physics_and_source_changes_rejected(self):
        self.cfg['seed'] += 1
        self.reg['cases']['B3600']['config_sha256'] = digest(self.cfg)
        self.sync()
        with self.assertRaisesRegex(HarnessError, 'B_restart_case'): self.validate()
        self.cfg['seed'] -= 1
        self.reg['cases']['B3600']['config_sha256'] = digest(self.cfg)
        self.fp['files']['src/smt_fullfab/harness/transport.py'] = '0' * 64
        self.fp['sha256'] = digest({k:v for k,v in self.fp.items() if k != 'sha256'})
        self.reg['fingerprint_sha256'] = self.fp['sha256']
        self.sync()
        with self.assertRaisesRegex(HarnessError, 'B_restart_source'): self.validate()

    def test_T22_original_twenty_cannot_be_replaced(self):
        self.gate['cases'].pop('micro-20')
        self.sync()
        with self.assertRaisesRegex(HarnessError, 'B_restart_entry'): self.validate()

    def test_T23_one_new_B_no_quota_or_cost_reset(self):
        for quota in (1, 2, 4):
            self.reg['full_B_new_run_limit'] = self.grant['full_B_new_run_limit'] = quota
            self.sync()
            with self.assertRaisesRegex(HarnessError, 'B_restart_budget'): self.validate()
        self.reg['full_B_new_run_limit'] = self.grant['full_B_new_run_limit'] = 3
        self.grant['prior_exception_count'] = 0
        self.sync()
        with self.assertRaisesRegex(HarnessError, 'B_restart_budget'): self.validate()
        self.grant['prior_exception_count'] = 14
        self.reg['carried_usage_at_registration']['combined']['tokens'] = 0
        self.sync()
        with self.assertRaisesRegex(HarnessError, 'B_restart_budget'): self.validate()

    def test_T23_zero_unknown_B_rule_retained(self):
        self.reg['B_early_stop_on_new_unknown_usage'] = False
        with self.assertRaisesRegex(HarnessError, 'B_restart_budget'): self.validate()

    def test_T23_all_previous_calls_and_failure_identities_count_once(self):
        usage, starts, identities = carried_costs(self.reg)
        self.assertEqual(usage, self.usage)
        self.assertEqual((starts, len(identities), carried_recovery_count(self.reg)), (2, 87, 14))
        self.assertEqual((usage['combined']['attempts'], usage['combined']['tokens'], usage['combined']['unknown_usage']), (352, 12045684, 25))

    def test_T23_diagnostic_failure_cannot_be_hidden(self):
        audit = checked_file(self.reg['diagnostics'])
        older = checked_file(audit['previous_cost_boundary'])
        reference = older['call_identities'][1]['result']
        bad = {**checked_file(reference), 'unknown_usage': False, 'usage': {'input_tokens': 0, 'output_tokens': 0}}
        def read(ref): return bad if ref == reference else checked_file(ref)
        with patch('src.smt_fullfab.harness.experiment.checked_file', side_effect=read):
            with self.assertRaisesRegex(HarnessError, 'diagnostic_cost'): verify_attempt(reference, model=MODEL)
        with self.assertRaisesRegex(HarnessError, 'diagnostic_batch'):
            verify_chain(self.reg['diagnostics'], model={'name': 'gpt-6.1-astra', 'reasoning_effort': 'medium'})

    def test_T20_TUN_environment_removes_all_explicit_proxies(self):
        source = {'HTTP_PROXY':'old', 'https_proxy':'old', 'All_Proxy':'old', 'no_proxy':'localhost', 'PATH':'keep'}
        result = apply_environment(source, self.reg['transport_proxy'])
        self.assertEqual(result, {'PATH':'keep','NO_PROXY':'*','no_proxy':'*'})
        self.assertEqual(source['HTTP_PROXY'], 'old')
        self.assertEqual(apply_environment({}, {'url':'http://127.0.0.1:1234'})['HTTPS_PROXY'], 'http://127.0.0.1:1234')

    def test_T20_TUN_off_or_DNS_change_prevents_real_admission(self):
        binding = checked_file(self.reg['transport_proxy']['binding'])
        with patch('src.smt_fullfab.harness.network_tun.current_route', return_value={**binding['route'], 'tun_enabled':False}):
            with self.assertRaisesRegex(HarnessError, 'network_unavailable'): validate_binding(self.reg['transport_proxy'], live=True)
        with patch('src.smt_fullfab.harness.network_tun.current_route', return_value=binding['route']), \
             patch('src.smt_fullfab.harness.network_tun.configuration_hashes', return_value={**binding['configuration_hashes'], 'dns_config_sha256':'0'*64}):
            with self.assertRaisesRegex(HarnessError, 'network_unavailable'): validate_binding(self.reg['transport_proxy'], live=True)


if __name__ == '__main__':
    unittest.main()
