"""Complete public-state snapshot and real-token fail-closed check; no sealed alias."""
import json
import pytest
from mac_fixture import environment
from harness_v6.ledger import ledger_read_view
from harness_v6.snapshot import stable_prefix,build_snapshot,tiktoken_counter,SnapshotBudgetExceeded


def test_public_complete_snapshot_and_budget():
    env,b=environment()
    observed=env.ledger_snapshot()
    ledger=ledger_read_view(observed['problem'],observed['plan'],observed['receipts'])
    prefix=stable_prefix(tool_descriptions=['read_entities','validate_plan','submit_plan','get_decision_snapshot'],
        routing=env.manifest['routes'],machine_groups=env.manifest['machines'])
    count=tiktoken_counter()
    args=dict(state_version=0,running_jobs=[dict(job=i,machine=j['machine'],lot_ids=j['lots'],started_at=j['start'])
        for i,j in sorted(env.jobs.items()) if not j['done']],last_cycle_receipt=None,model_notes='public mechanism',token_counter=count)
    payload=build_snapshot(prefix,ledger,token_budget=10**8,**args)
    current=json.loads(payload.split(b'\n',1)[1])
    assert current['pending_tasks']==ledger.pending_tasks()
    assert current['holds']==list(ledger.holds.values())
    expected={oid for oid,r in ledger.rows().items() if r['ready'] and r['state']=='ready_unreserved'}
    assert {r['operation_id'] for r in current['unreserved_ready']}==expected
    tokens=count(payload.decode())
    with pytest.raises(SnapshotBudgetExceeded) as error:
        build_snapshot(prefix,ledger,token_budget=tokens-1,**args)
    assert error.value.report['tokens']==tokens and error.value.report['dropped_rows']==0
