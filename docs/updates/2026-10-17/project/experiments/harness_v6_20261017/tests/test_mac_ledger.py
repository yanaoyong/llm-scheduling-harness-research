from mac_fixture import environment
from harness_v6.ledger import ledger_from_scratch,choose_batch

def test_physical_legal_reconciliation():
    env,b=environment()
    problem=env.problem();ledger=ledger_from_scratch(problem)
    differences=[]
    rows=ledger.rows()
    ops={k:v for k,v in ledger.operations.items() if rows[k]['ready']}
    for machine in problem['machines']:
        mid=machine['machine']
        public=not machine.get('currently_busy') and not machine.get('currently_down') and bool(choose_batch(ops,machine))
        physical=env.has_legal(mid)
        if public!=physical:differences.append({'machine':mid,'public':public,'physical':physical})
    assert differences==b['documented_public_physical_differences']
