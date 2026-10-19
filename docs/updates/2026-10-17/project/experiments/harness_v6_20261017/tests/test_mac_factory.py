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


def test_public_atomic_store(tmp_path):
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from harness_v6.factory_v6 import capture,commit_physical
    from harness_v6.store_v6 import Store
    env,b=environment('when_ready');before=capture(env);plan=b['when_ready']['plan']
    with TemporaryDirectory(dir=tmp_path) as directory:
        root=Path(directory);store=Store(root/'store',root=root,create=True)
        try:
            adopted=commit_physical(store,0,env,plan)
            assert adopted is not None and store.meta('state_version')==1
            assert capture(env)==before
            assert store.read('physical_states','1')==capture(adopted)
            assert commit_physical(store,0,env,plan) is None
            assert store.meta('state_version')==1 and store.read('plans','1')==plan
        finally:store.close()
