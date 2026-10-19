"""Portable scratch paths preserve the source/evidence write boundary."""
from pathlib import Path
import pytest
from harness_v6.work_paths import checked_output


def test_scratch_siblings_are_allowed(tmp_path):
    assert checked_output(tmp_path/'sealed', tmp_path,
                          inputs=(tmp_path/'inputs', tmp_path/'public.json')) == tmp_path/'sealed'


@pytest.mark.parametrize('relative', ['.', '..', '../escape'])
def test_output_cannot_escape_work_root(tmp_path, relative):
    with pytest.raises(ValueError, match='child'):
        checked_output(tmp_path/relative, tmp_path)


def test_symlink_cannot_redirect_output_into_evidence(tmp_path):
    source=tmp_path/'evidence'; source.mkdir()
    (tmp_path/'alias').symlink_to(source, target_is_directory=True)
    with pytest.raises(ValueError, match='overlap'):
        checked_output(tmp_path/'alias'/'generated', tmp_path, inputs=(source,))


def test_output_cannot_contain_inputs(tmp_path):
    with pytest.raises(ValueError, match='overlap'):
        checked_output(tmp_path/'sealed', tmp_path, inputs=(tmp_path/'sealed'/'original',))


def test_work_root_cannot_be_checkout():
    with pytest.raises(ValueError, match='repository'):
        checked_output(Path(__file__).resolve().parents[1]/'output', Path(__file__).resolve().parents[1])
