from mac_fixture import bundle
from harness_v6.audit_v6 import audit_plan_sources,audit_opportunity_coverage

def test_time_semantics():
    b=bundle('v6_time_semantics_trace');audit=audit_plan_sources(b['v6_time_semantics_trace'])
    assert audit['valid'],audit['errors']

def test_ledger_metrics():
    b=bundle('v6_trace','independent_idle_integrals');audit=audit_opportunity_coverage(b['v6_trace'])
    assert audit['steps']>0 and audit['valid'],audit
    assert audit['integrals']==b['independent_idle_integrals']
