from mac_fixture import environment, bundle
from harness_v6.replay import equivalence

def test_equivalence():
    bundle("mixed_702", "g0_committed_plans", "g0_trace")
    env,b=environment("mixed_702")
    result=equivalence(env,b['g0_committed_plans'],b['g0_trace'])
    assert result['time']==1603.10 and result['events']>0
    assert result['valid'],result['errors']
