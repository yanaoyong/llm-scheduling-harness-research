"""Hashed atomic segment checkpoints and a durable in-flight recovery marker."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile
import io
import tarfile
import shutil
from .snapshot import canonical


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sha(data):
    return hashlib.sha256(data).hexdigest()


class CheckpointStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def save(self, segment, *, state, cycle, ledger, cumulative_costs, extra=None):
        payload = {'schema': 'harness-v6-checkpoint-1', 'segment': segment, 'state': state,
                   'cycle': cycle, 'ledger': ledger, 'cumulative_costs': cumulative_costs, 'extra': extra or {}}
        payload['previous'], chain_size = self._chain_tail()
        if payload['previous'] is None and segment != 0:
            raise ValueError('checkpoint chain must start at segment 0')
        data = canonical(payload)
        name = 'checkpoint-' + str(segment) + '-' + sha(data) + '.json'
        atomic_write(self.directory / name, data)
        entry = {'segment': segment, 'file': name, 'sha256': sha(data),
                 'previous_sha256': payload['previous']['sha256'] if payload['previous'] else None}
        with (self.directory / 'chain.jsonl').open('a+b') as stream:
            # A newline commits a record; discard an interrupted final append.
            stream.truncate(chain_size)
            stream.write(canonical(entry) + b'\n'); stream.flush(); os.fsync(stream.fileno())
        keep = {name}
        if payload['previous']:
            keep.add(payload['previous']['file'])
        for path in self.directory.glob('checkpoint-*.json'):
            if path.name not in keep:
                path.unlink()
        return payload

    def _chain_tail(self):
        """Verify committed metadata links, ignoring an unterminated final line."""
        chain = self.directory / 'chain.jsonl'
        raw = chain.read_bytes() if chain.exists() else b''
        size = raw.rfind(b'\n') + 1
        tail = None
        for line in raw[:size].splitlines():
            entry = json.loads(line)
            previous = tail['sha256'] if tail else None
            if entry['previous_sha256'] != previous or (tail is None and entry['segment'] != 0):
                raise ValueError('checkpoint chain hash mismatch')
            if Path(entry['file']).name != entry['file']:
                raise ValueError('invalid checkpoint chain manifest')
            tail = entry
        return tail, size

    def has_checkpoint(self):
        """Return whether the authoritative chain has a committed record."""
        tail, _ = self._chain_tail()
        return tail is not None

    def latest(self):
        manifest, _ = self._chain_tail()
        if manifest is None:
            raise FileNotFoundError('no complete checkpoint chain record')
        data = (self.directory / manifest['file']).read_bytes()
        if sha(data) != manifest['sha256']:
            raise ValueError('checkpoint hash mismatch')
        payload = json.loads(data)
        expected = payload['previous']['sha256'] if payload['previous'] else None
        if expected != manifest['previous_sha256'] or payload['segment'] != manifest['segment']:
            raise ValueError('checkpoint chain hash mismatch')
        return payload

    def mark_inflight(self, bundle):
        """Call before launching a session; refresh after observed usage/submit.

        Bundle contains state, ledger, cycle.capture(), submit.capture(), metrics.
        A pending submission is never an adopted state. Costs known at the last
        durable update survive; an interrupted session adds unknown usage.
        """
        if bundle['submit'].get('finalized'):
            raise ValueError('inflight marker requires an unfinalized submitter')
        data = canonical(bundle)
        atomic_write(self.directory / 'inflight.json', canonical({'sha256': sha(data), 'bundle': bundle}))

    def clear_inflight(self):
        atomic_write(self.directory / 'inflight.json', canonical(None))

    def recover(self):
        payload = self.latest()
        marker_path = self.directory / 'inflight.json'
        marker = json.loads(marker_path.read_bytes()) if marker_path.exists() else None
        if not marker:
            return payload
        bundle = marker['bundle']
        if sha(canonical(bundle)) != marker['sha256']:
            raise ValueError('inflight hash mismatch')
        from .cycle import CycleMachine
        from .submit import Submitter
        machine = CycleMachine.restore(bundle['cycle'])
        # A published completion checkpoint supersedes an uncleared WAL marker.
        saved = payload['cycle']
        if saved['cycles'] >= machine.cycles and saved['inflight'] is None:
            self.clear_inflight()
            return payload
        submit = Submitter.restore(bundle['submit'])
        old_plan = submit.finalize(process_ok=False, usage_known=False)
        known = bundle.get('session_usage', {})
        machine.finish(submitted=False, process_ok=False, usage_known=False,
                       cost=known.get('cost', 0), wall_seconds=known.get('wall_seconds', 0), model_note=bundle.get('model_note', ''))
        state = bundle['state']
        state['plan'] = old_plan
        extra = dict(bundle.get('extra', {}))
        if 'metrics' in extra:
            from .metrics import Metrics
            metrics = Metrics.restore(extra['metrics'])
            usage = {k: v for k, v in known.items() if k in (
                'tool_calls', 'tool_rounds', 'input_tokens', 'cached_tokens',
                'output_tokens', 'model_seconds', 'wall_seconds', 'submit_attempts', 'submit_rejections')}
            metrics.session(machine.now, failed=True, usage_known=False, **usage)
            extra['metrics'] = metrics.capture()
        if 'history' in extra:
            from .snapshot import HistorySummary
            extra['history'] = HistorySummary(extra['history']).append({'adopted': False}).digest
        extra['recovered_inflight'] = True
        payload = dict(segment=machine.segment, state=state, cycle=machine.capture(),
                            ledger=bundle['ledger'], cumulative_costs={'cost': machine.cost,
                            'wall_seconds': machine.wall_seconds, 'unknown_usage': machine.unknown_usage}, extra=extra)
        return payload

    def rotate_logs(self, segment, logs):
        """Compress exact segment bytes; callers pass closed segment log paths.

        Originals are removed only after an atomic, hashed manifest is durable.
        """
        records = []
        for kind, source in sorted(logs.items()):
            if kind == 'cycles':
                buffer = io.BytesIO()
                with tarfile.open(fileobj=buffer, mode='w') as archive:
                    for directory in sorted(source):
                        archive.add(directory, arcname=directory.name)
                raw = buffer.getvalue()
            elif kind not in ('trace', 'mcp', 'jsonl'):
                raise ValueError('unknown log kind')
            else:
                raw = Path(source).read_bytes()
            packed = gzip.compress(raw, compresslevel=1, mtime=0)
            name = f'{kind}-{segment}.tar.gz' if kind == 'cycles' else f'{kind}-{segment}.jsonl.gz'
            atomic_write(self.directory / name, packed)
            records.append({'kind': kind, 'file': name, 'sha256': sha(packed),
                            'raw_sha256': sha(raw), 'raw_bytes': len(raw)})
        atomic_write(self.directory / f'logs-{segment}.json', canonical(records))
        for source in logs.values():
            if isinstance(source, list):
                for directory in source:
                    shutil.rmtree(directory)
            else:
                Path(source).unlink()
        return records


def capture_ledger(ledger):
    """Save ordered input tables; no JSON object integer keys or set indexes."""
    from copy import deepcopy
    return deepcopy({'time': ledger.now, 'plan_created_at': ledger.plan_created_at,
            'hold_keys': list(ledger.holds),
            **{name: {'upsert': list(getattr(ledger, name).values())}
               for name in ('operations', 'machines', 'tasks', 'holds', 'receipts', 'task_receipts')}})


def restore_ledger(state):
    from .ledger import Ledger, ledger_apply
    ledger = ledger_apply(Ledger(state['time']), {k: v for k, v in state.items() if k != 'holds'})
    from copy import deepcopy
    ledger.holds = dict(zip(state['hold_keys'], deepcopy(state['holds']['upsert'])))
    return ledger
