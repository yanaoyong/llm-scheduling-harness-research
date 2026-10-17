"""Acquire only this experiment's gate after a complete model request."""
from pathlib import Path
import fcntl,time,sqlite3,json
O=Path(__file__).resolve().parent
reg=json.loads((O/'experiment.json').read_text())
with (O/'writer.lock').open('a+b') as lock:
 while True:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
  except BlockingIOError:time.sleep(.2)
 rows=[]
 for case in reg['execution_order']:
  db=sqlite3.connect(f'file:{O}/runs/{case}/events.sqlite3?mode=ro',uri=True)
  head=json.loads(db.execute("SELECT value FROM metadata WHERE key='head'").fetchone()[0]);refs=dict(db.execute("SELECT key,ref FROM records WHERE namespace='attempts'"));db.close()
  rows.append({'case':case,'head':head,'attempt_refs':refs})
 # The outer runner will fail its next nonblocking admission without reserving a call.
 # A just-committed plan is allowed to finish its ordinary advance first.
 time.sleep(3)
 (O/'count_revision_gate.json').write_text(json.dumps({'epoch':time.time(),'reason':'User-authorized removal of hard call-count caps at a completed-request boundary','cases':rows,'only_this_experiment_gate':True,'model_process_interrupted':False},ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'gate_acquired':True,'heads':[r['head']['phase'] for r in rows],'only_this_experiment':True}))
