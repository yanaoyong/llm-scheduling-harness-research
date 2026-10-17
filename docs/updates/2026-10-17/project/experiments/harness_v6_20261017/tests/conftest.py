"""Live host fixtures use tmpfs for durable synthetic I/O when available."""
import tempfile
from pathlib import Path
import pytest

@pytest.fixture(autouse=True)
def live_tmpfs(request, monkeypatch, tmp_path):
    if request.module.__name__ not in ('test_live', 'test_synthetic_long_run', 'test_groups', 'test_metrics_checkpoint', 'test_checkpoint_segments') or 'mac' in request.node.name:
        yield tmp_path
        return
    root = Path('/dev/shm')
    with tempfile.TemporaryDirectory(dir=root if root.is_dir() else tmp_path) as directory:
        monkeypatch.setattr(tempfile, 'tempdir', directory)
        yield Path(directory)

@pytest.fixture
def live_dir(live_tmpfs):
    return live_tmpfs
