"""Read-only assembly of sealed results, retaining the approved retry lineage."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from src.smt_fullfab.harness.offline_isolation import install_guard
install_guard()
from src.smt_fullfab.harness.evaluation import Evidence,audit_provenance,audit_cost,audit_physical_prefix
from src.smt_fullfab.harness.capacity_config import audit_policy
from src.smt_fullfab.metrics import compute_metrics
from extended_lineage_audit import verify_inheritance
from capacity_retry_support import audit_retry
from run_extended_three_group_pilot import isolation
BASE=ROOT/'live_pilots/extended_three_group_20261017'
RUN=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else BASE
RETRY=ROOT/'live_pilots/extended_three_group_capacity_retry_20261017'
def read(p):return json.loads(p.read_text())
def main():
 results={}
 for g in ('G0','G1','G2'):
  source=RETRY if g=='G1' and RUN==BASE else RUN
  result=read(source/(g+'.result.json'));result['evidence_directory']=result.get('evidence_directory',str(source/g));results[g]=result
 end=min(r['head']['time'] for r in results.values())
 for g,r in results.items():
  ev=Evidence(r['evidence_directory'],r['evidence_sha256']);trace=[ev.get(h) for h in ev.value['physical']];cfg=ev.manifest['config']
  r['inheritance_audit']=verify_inheritance(ev);r['provenance_audit']=audit_provenance(ev,trace);r['cost_audit']=audit_cost(ev)
  if g=='G1':r['approved_retry_audit']=audit_retry(ev)
  if ev.rows('approved_connection_retry'):
   from connection_retry_support import audit as connection_audit
   r['approved_connection_retry_audit']=connection_audit(ev)
  if ev.rows('deadline_reconciliations'):
   from deadline_completion_support import audit as deadline_audit
   r['deadline_reconciliation_audit']=deadline_audit(ev)
  if ev.rows('resource_continuations'):
   from extended_resource_continuation import audit
   r['resource_continuation_audit']=audit(ev)
  if '64_to_96' in ev.rows('resource_continuations'):
   from extended_resource_final_segment import audit as final_audit
   r['final_resource_audit']=final_audit(ev)
  audit=audit_physical_prefix(trace,r['head']['time'],cfg['priority_weights'],batching_policy=audit_policy(cfg['capacity_experiment'],702))
  r['physical_prefix_errors']=audit['errors'];r['opportunity_audit']=audit['opportunity_audit']
  r['own_observed_metrics']=compute_metrics(trace,window_start=702,window_end=r['head']['time'],priority_weights=cfg['priority_weights'])
  r['common_metrics']=compute_metrics(trace,window_start=702,window_end=end,priority_weights=cfg['priority_weights'])
  r['initial_backlog']=read(RUN/(g+'.initial_backlog.json'))
 out={'common_window':[702,end],'target_window':[702,1800],'results':results,'isolation_after':isolation(),
      'limitations':['A single paired continuation; all prior outputs and costs retained.',
       'G1 retains every separately user-approved failure retry. Failed attempts and unknown usage remain included; reported tokens are a lower bound.',
       'Common-window metrics must be separated from expenditure after the common endpoint.',
       'Simulation pauses for model decisions; reported simulated waiting excludes real model latency.',
       'A partial physical trace is expected to lack the terminal event. No terminal is fabricated.']}
 (RUN/'comparison.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'common_window':out['common_window'],'actual_endpoints':{g:r['head']['time'] for g,r in results.items()},'isolation':out['isolation_after']}))
if __name__=='__main__':main()
