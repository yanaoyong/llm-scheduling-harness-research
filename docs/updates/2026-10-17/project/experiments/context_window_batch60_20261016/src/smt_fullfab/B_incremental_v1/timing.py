"""One explicit runtime timer; no authentication, scheduling or process launch."""
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import threading

_TELEMETRY_SHA='6220ba72e21ad3bcdd2449f1b9d8e2bc8daf68cc958c0b81d931dc85ecd506d3'
_p=Path(__file__).with_name('telemetry.py');_raw=_p.read_bytes()
if hashlib.sha256(_raw).hexdigest()!=_TELEMETRY_SHA:
    raise RuntimeError('telemetry original bytes differ')
_spec=importlib.util.spec_from_file_location('_B_timed_telemetry',_p)
telemetry=importlib.util.module_from_spec(_spec)
exec(compile(_raw,str(_p),'exec'),telemetry.__dict__)


class TimingError(RuntimeError):
    """Diagnostic failure, deliberately not a domain ValueError/KeyError."""


class RuntimeTiming:
    def __init__(self, emit, *, clock_ns=None):
        self.owner_pid=os.getpid();self.owner_thread=threading.current_thread()
        self.failed=False;self.failure=None;self.primary_failure=None;self.serial=0
        self.emit=emit;self.binding={'operation_id':'runtime','call_id':None}
        self.timer=telemetry.StageTimer(self._emit,**({} if clock_ns is None else {'clock_ns':clock_ns}))

    def _owner(self):
        if os.getpid()!=self.owner_pid or threading.current_thread() is not self.owner_thread:
            self.failed=True;self.failure='timer owner PID/thread changed'
            raise TimingError(self.failure)

    def ready(self):
        self._owner()
        if self.failed or self.timer.closed:
            raise TimingError('diagnostic timer poisoned or closed: '+str(self.failure))

    def _diagnostic_failure(self, exc):
        self.failed=True;self.failure=type(exc).__name__+': '+str(exc)
        if isinstance(exc,Exception):
            raise TimingError(self.failure) from exc
        raise exc

    def _emit(self, row):
        try:
            self._owner();self.emit(row)
        except BaseException as exc:
            self._diagnostic_failure(exc)

    @contextmanager
    def context(self, *, operation_id, call_id=None):
        self.ready();old=self.binding
        if type(operation_id)is not str or not operation_id or (call_id is not None and (type(call_id)is not str or not call_id)):
            raise TimingError('explicit operation ID and optional original call ID required')
        self.binding={'operation_id':operation_id,'call_id':call_id}
        try:yield self
        finally:self.binding=old

    def bind_call(self, call_id):
        self.ready()
        if type(call_id)is not str or not call_id:raise TimingError('original call ID required')
        self.binding={**self.binding,'call_id':call_id}

    def call(self, stage, reason, function, *args, **kwargs):
        self.ready()
        try:
            token=self.timer.begin(stage,**self.binding,reason=reason)
        except BaseException as exc:
            self._diagnostic_failure(exc)
        try:
            result=function(*args,**kwargs)
        except BaseException as primary:
            try:self.timer.end(token,outcome='error',error_type=type(primary).__name__)
            except BaseException as secondary:
                self.failed=True;self.failure=type(secondary).__name__+': '+str(secondary)
                self.primary_failure=primary
                primary.add_note('timing diagnostic close failed: '+type(secondary).__name__+': '+str(secondary))
            raise
        else:
            try:self.timer.end(token)
            except BaseException as exc:self._diagnostic_failure(exc)
            return result

    def finish(self):
        self.ready()
        try:return self.timer.finish()
        except BaseException as exc:self._diagnostic_failure(exc)

    def diagnostic_state(self):
        return {'failed':self.failed,'failure':self.failure,'owner_pid':self.owner_pid,
                'closed':self.timer.closed,'cpu_time_measured':False,
                'original_exception_type':None if self.primary_failure is None else type(self.primary_failure).__name__}


class JsonlSink:
    """Create-new, checked write/fsync; caller includes this file in whole cost."""
    def __init__(self, path):
        self.path=Path(path)
        self.stream=self.path.open('xb');self.closed=False

    def __call__(self, row):
        if self.closed:raise TimingError('diagnostic sink closed')
        raw=(json.dumps(row,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
        written=self.stream.write(raw)
        if type(written)is not int or written!=len(raw):raise OSError('diagnostic sink short write')
        self.stream.flush();os.fsync(self.stream.fileno())

    def close(self):
        if not self.closed:
            self.closed=True;self.stream.close()


def call(timer, stage, reason, function, *args, **kwargs):
    return function(*args,**kwargs) if timer is None else timer.call(stage,reason,function,*args,**kwargs)


def open_timing(path, *, clock_ns=None):
    sink=JsonlSink(path)
    try:return sink,RuntimeTiming(sink,clock_ns=clock_ns)
    except BaseException as primary:
        try:sink.close()
        except BaseException as secondary:
            primary.add_note('timing sink close after initialization failed: '+type(secondary).__name__)
        raise
