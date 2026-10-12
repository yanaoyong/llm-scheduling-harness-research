#!/usr/bin/env python3
"""Non-model full-factory development pilot. Never labels FIFO or fake calls as B/C."""
import argparse,json,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.smt.environment import SmtEnvironment
from src.smt.optimizer import solve_action

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--seed',type=int,default=701);ap.add_argument('--hours',type=float,default=8);ap.add_argument('--run-dir',required=True);ap.add_argument('--data-dir');a=ap.parse_args()
 p=ROOT/a.run_dir;p.mkdir(parents=True,exist_ok=False);start=time.process_time();result={'phase':'development','arm':'A-pilot','model_calls':0,'seed':a.seed,'hours':a.hours}
 try:
  e=SmtEnvironment(seed=a.seed,window_seconds=a.hours*3600,data_dir=a.data_dir,trace_path=p/'trace.jsonl');s=e.advance();n=0;solver_seconds=0
  while not s['finished']:
   if time.process_time()-start>180:raise RuntimeError('pilot 180 CPU second limit')
   (p/f'state_{n:03}.json').write_text(json.dumps(s,indent=2));r=solve_action(s);solver_seconds+=r['wall_seconds'];(p/f'decision_{n:03}.json').write_text(json.dumps(r,indent=2));s=e.apply(r['action']);n+=1
  result.update(status='success',metrics=e.finish(),solver_seconds=solver_seconds)
 except Exception as exc:
  result.update(status='failed',error=repr(exc),traceback=traceback.format_exc())
 result['cpu_seconds']=time.process_time()-start;(p/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
 if result['status']!='success':return 1
 from src.smt.audit import audit_trace
 audit=audit_trace(p/'trace.jsonl',verify_data_dir=e.data_dir);(p/'audit.json').write_text(json.dumps(audit,indent=2));print(json.dumps(audit,indent=2));return 0 if audit['valid'] else 2
if __name__=='__main__':raise SystemExit(main())
