"""Bound this experiment copy to local replay; never acquire an external run."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[3]
_installed = False


def local_path(path):
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(ROOT):
        from .contracts import HarnessError
        raise HarnessError('isolated_copy_only', 'Run/output must stay inside the independent copy')
    return resolved


def reject_model_calls():
    from .contracts import HarnessError
    raise HarnessError('offline_only', 'This experiment is authorized for offline validation only')


def authorize_model(config, admission):
    # Offline remains the default. Only the separately frozen paired pilot can
    # enter the real transport; a boolean flag alone grants nothing.
    from .capacity_pilot import is_pilot, registration
    if not is_pilot(admission) or not (config.get('capacity_experiment') or {}).get('model_calls_enabled'):
        reject_model_calls()
    registration(admission, config=config)


def install_guard():
    """Process-local guard. Does not change host configuration or another process."""
    global _installed
    if _installed:
        return
    _installed = True
    def guard(event, args):
        if event.startswith('socket.') or event in ('subprocess.Popen', 'os.system', 'os.posix_spawn'):
            raise RuntimeError('offline_only: network and child processes are disabled')
        if event == 'open':
            path, mode, flags = args
            writes = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if writes and isinstance(path, (str, bytes, os.PathLike)):
                local_path(os.fsdecode(path))
        if event in ('os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.utime'):
            local_path(args[0])
        if event in ('os.rename', 'os.link', 'os.symlink'):
            local_path(args[0]); local_path(args[1])
    sys.addaudithook(guard)

