"""Tamper with copies of real trace evidence; verify semantic rejection."""
import sys,json,tempfile,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'experiment_round2_3datasets';OUT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT))
from src.smt_fullfab.trace_source import inspect_jsonl,scan_envelope
from src.smt_fullfab.stream_source_audit import audit_plan_sources
from src.smt_fullfab.stream_opportunity_audit import audit_opportunity_coverage
from src.smt_fullfab.stream_physical_core import audit_events
p=ROOT/'runs/smt_fullfab_development/A_1701_1h_hybrid_v1/trace.jsonl';base=[json.loads(x) for x in p.read_text().splitlines()];report={}
with tempfile.TemporaryDirectory(prefix='abc_negative_') as td:
 td=Path(td)
 def save(name,events):
  p=td/name
  with p.open('w') as f:
   for e in events:f.write(json.dumps(e,separators=(',',':'))+'\n')
  return p
 p=save('no_terminal.jsonl',base[:-1])
 try:scan_envelope(inspect_jsonl(p),require_terminal=True);report['missing_terminal']={'rejected':False}
 except Exception as exc:report['missing_terminal']={'rejected':True,'error':str(exc)}
 mutant=copy.deepcopy(base);target=next(x for x in mutant if x['kind']=='dispatch' and x.get('owner')=='plan');target['plan_task_id']='NONEXISTENT_AUDIT_TASK'
 r=audit_plan_sources(inspect_jsonl(save('wrong_task.jsonl',mutant)),report_path=td/'wrong_task_report.json')
 report['false_plan_provenance']={'rejected':not r['valid'],'errors':r['errors'][:5]}
 mutant=copy.deepcopy(base);target=next(x for x in mutant if x['kind']=='time_advance');target['to']=3600
 r=audit_opportunity_coverage(inspect_jsonl(save('jump.jsonl',mutant)),report_path=td/'jump_report.json')
 report['time_advance_skips_boundaries']={'rejected':not r['valid'],'errors':r['errors'][:5]}
 physical=[json.loads(x) for x in (OUT/'A_bundle/projection/physical.jsonl').read_text().splitlines()]
 target=next(x for x in physical if x['kind']=='dispatch' and x.get('owner')=='controller');target['processing_seconds']+=1
 r=audit_events(iter(physical),verify_data_dir=ROOT/'data/smt/SMT2020_LVHM')
 report['false_processing_duration']={'rejected':not r['valid'],'errors':r['errors'][:5]}
(OUT/'negative_controls.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False));assert all(x['rejected'] for x in report.values())
