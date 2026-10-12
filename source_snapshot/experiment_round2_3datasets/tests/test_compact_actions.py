import unittest
from src.agents.static import decode_order,ActionError,compact_problem
from tests.test_solver import small_problem

class CompactTests(unittest.TestCase):
    def test_same_decisions_same_schedule(self):
        p=small_problem()
        compact=[[0,1],[1,0],[0,0],[1,1]]
        explicit=[{'id':'j0o0','machine':1},{'id':'j1o0','machine':0},
                  {'id':'j0o1','machine':0},{'id':'j1o1','machine':1}]
        self.assertEqual(decode_order(p,compact),decode_order(p,explicit))
        self.assertEqual(compact_problem(p)['jobs'][0][0],[[0,3],[1,2]])

    def test_invalid_compact_not_repaired(self):
        for actions in [[[0,0],[0,0],[0,0],[1,1]],[[8,0],[1,0],[0,0],[1,1]],
                        [[0,True],[1,0],[0,0],[1,1]]]:
            with self.assertRaises(ActionError):decode_order(small_problem(),actions)
