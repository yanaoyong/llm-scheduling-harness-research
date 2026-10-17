"""The new capacity run also requires its complete outer resource certificate."""
from unittest.mock import patch
from tests.test_smt_fullfab_offline_A_status import OfflineAStatusTests as _Base
from src.smt_fullfab.status import apply_offline_A_gate


class OfflineACapacityStatusTests(_Base):
    def setUp(self):
        super().setUp()
        new=self.run.with_name('A_1701_8h_hybrid_v3')
        self.run.rename(new);self.run=new

    def check(self, verified=None, folder=None, row=None):
        with patch('src.smt_fullfab.offline_A_gate_v3.read_acceptance',
                   return_value=self.verified if verified is None else verified):
            return apply_offline_A_gate(self.row if row is None else row,
                                        self.run if folder is None else folder,root=self.root)


del _Base  # unittest discovers only this version's subclass, seven inherited cases.
