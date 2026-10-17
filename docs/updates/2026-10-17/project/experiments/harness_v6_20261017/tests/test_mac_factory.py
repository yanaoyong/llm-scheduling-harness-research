from mac_fixture import environment
from harness_v6.contracts import digest

def test_roundtrip():
    env,b=environment()
    from harness_v6.factory_v6 import capture,restore
    state=capture(env)
    assert 'batch_state' not in state
    clone=restore(state,env.trace,data_dir=b['data_dir'])
    assert digest(capture(clone))==digest(state)
    assert clone.trace==env.trace
