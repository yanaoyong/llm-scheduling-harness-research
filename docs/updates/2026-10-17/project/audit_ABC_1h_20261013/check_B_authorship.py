"""Read-only raw-output to delta to committed-plan checks, plus raw usage summation."""
import json,hashlib,sys,collections,base64,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'experiment_round2_3datasets';OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from src.smt_fullfab.plan_delta import compile_plan_delta
from src.smt_fullfab.B_incremental_v3 import durable
refs={}
def read(p):
 p=Path(p);raw=p.read_bytes();refs[str(p.relative_to(ROOT))]=hashlib.sha256(raw).hexdigest();return json.loads(raw)
def digest(d):return hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
def need(x,msg):
 if not x:raise ValueError(msg)
versions=['v7','v7__recovery_001','v8','v8__launch_recovery_001','v8__preserved_001','v9__memory_progress_001','v9__memory_progress_002','v9__memory_progress_003','v10__working_set_001','v11__execution_feedback_001','v11__execution_feedback_002','v12__commit_progress_001','v13__base_evidence_002','v14__candidate_paths_001','v15__authorized_extension_001']
runs=[ROOT/'runs/smt_fullfab_stage2'/('B_1701_1h_delta_'+v) for v in versions]
ledgerpath=ROOT/'runs/smt_fullfab_B_direct_gate/B_1701_1h_delta_v15__authorized_extension_001/ledger_final.jsonl'
raw=ledgerpath.read_bytes();refs[str(ledgerpath.relative_to(ROOT))]=hashlib.sha256(raw).hexdigest();ledger=[json.loads(s) for s in raw.splitlines()]
reserves={x['call_id']:x for x in ledger if x.get('event')=='reserve'};finishes={x['call_id']:x for x in ledger if x.get('event')=='finish'}
bycall={};cost=collections.Counter();unknown=[];errors=[];native=[]
for run in runs:
 for p in sorted(run.glob('model_*/result.json')):
  d=read(p);cid=d['call_id'];need(cid not in bycall,'duplicate call ID');bycall[cid]=(p.parent,d)
  need(cid in reserves and cid in finishes,'unclosed call '+cid)
  f=finishes[cid];need(f['status']==d['status'] and f['details']['usage']==d['usage'],'ledger result mismatch')
  need(Path(reserves[cid]['run_id']).resolve()==p.parent.resolve(),'ledger run differs')
  eraw=(p.parent/'events.jsonl').read_bytes();refs[str((p.parent/'events.jsonl').relative_to(ROOT))]=hashlib.sha256(eraw).hexdigest()
  summary=durable.event_summary(eraw)
  need(all(d.get(k)==v for k,v in summary.items()),'raw event summary differs '+str(p))
  if d.get('native_tool_events'):native.append(cid)
  cost['attempts']+=1;cost['status_'+d['status']]+=1;cost['model_active_seconds']+=d['duration_seconds']
  u=d.get('usage') or {}
  if type(u.get('input_tokens')) is int and type(u.get('output_tokens')) is int:cost['known_tokens']+=u['input_tokens']+u['output_tokens']
  else:unknown.append(cid)
print('B raw calls verified',cost['attempts'],flush=True)
# The first plan predates per-plan JSON exports. Rebuild its pure interaction from raw outputs.
run=runs[0];boot=read(run/'plan_00000/bootstrap.json');model=durable.fresh_session(boot)
for i in range(79):
 p=run/f'model_{i:05d}';d=read(p/'result.json');issued=model.next_prompt()
 need(issued['prompt']==(p/'prompt.txt').read_text(),'initial prompt replay differs '+str(i))
 model.handle((p/'final.txt').read_bytes(),call_id=d['call_id'],model_index=i)
first=model.export_evidence();need(first['selection'] is not None,'no selected initial plan')
print('B first plan pure replay verified',flush=True)
tracepath=runs[-1]/'physical/trace.jsonl';raw=tracepath.read_bytes();refs[str(tracepath.relative_to(ROOT))]=hashlib.sha256(raw).hexdigest()
commits=[e for e in map(json.loads,raw.splitlines()) if e['kind']=='plan_committed'];commit_map={digest(e['plan']):e for e in commits};need(len(commit_map)==95,'unexpected trace commitments')
verified=[]
for run in runs:
 for planpath in sorted(run.glob('plan_*/selected_plan.json')):
  plan=read(planpath);boot=read(planpath.parent/'bootstrap.json')
  ev=first if run==runs[0] else read(planpath.parent/'interaction_evidence.json')
  sel=ev['selection'];cand=sel['candidate'];prov=cand['provenance'];history={h['history_index']:h for h in ev['history']}
  def bound(ref):
   h=history[ref['history_index']];need(h['call_id']==ref['call_id'] and h['model_index']==ref['model_index'],'history identity differs')
   p,d=bycall[h['call_id']];raw=(p/'final.txt').read_bytes();refs[str((p/'final.txt').relative_to(ROOT))]=hashlib.sha256(raw).hexdigest()
   need(d['status']=='success' and raw==base64.b64decode(h['raw_output_base64']),'raw model output differs')
   need(hashlib.sha256(raw).hexdigest()==ref['raw_output_sha256']==h['raw_output_sha256'],'raw output hash differs')
   parsed=json.loads(raw);need(parsed==d['output']==h['parsed_envelope'],'parsed output differs')
   need(hashlib.sha256((p/'prompt.txt').read_bytes()).hexdigest()==ref['issued_prompt_sha256'],'prompt reference differs')
   events=[json.loads(s) for s in (p/'events.jsonl').read_text().splitlines()]
   messages=[e['item'].get('text') for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='agent_message']
   need(any(isinstance(m,str) and m.strip()==raw.decode().strip() for m in messages),'raw output absent from CLI agent message')
   return parsed['request']
  create=bound(prov['create']);need(create['kind']=='create_draft' and create['draft_id']==cand['draft_id'],'create differs')
  delta={};chunks=0;sealed=False
  for ref in prov['assembly_actions']:
   req=bound(ref);need(req['kind']=='assembly_action','wrong assembly');a=req['action'];need(a['draft_id']==cand['draft_id'],'draft differs')
   if a['action']=='seal':sealed=True;continue
   need(not sealed and a['action']=='chunk' and a['sequence']==chunks,'chunk order differs');chunks+=1
   for x in a['set_fields']:
    cursor=delta
    for k in x['path'][:-1]:cursor=cursor.setdefault(k,{})
    need(x['path'][-1] not in cursor,'field overwritten');cursor[x['path'][-1]]=x['value']
   for x in a['append_arrays']:
    cursor=delta
    for k in x['path'][:-1]:cursor=cursor.setdefault(k,{})
    cursor.setdefault(x['path'][-1],[]).extend(x['items'])
  need(sealed and delta==cand['delta'] and digest(delta)==cand['delta_sha256'],'raw chunks do not reconstruct candidate delta')
  check=bound(prov['check']);need(check['kind']=='check_assembly' and check['draft_id']==cand['draft_id'] and check['delta_sha256']==digest(delta),'check request differs')
  applied=bound(sel['selection_binding']);need(applied['kind']=='apply' and applied['candidate_id']==cand['candidate_id'] and applied['candidate_sha256']==digest(cand),'explicit apply differs')
  compiled=compile_plan_delta(boot['base_plan'],boot['problem'],boot['execution_state'],delta,source_sha256=boot['source_sha256'])
  need(compiled==cand['compiled'] and compiled['plan']==plan,'pure compile does not match committed plan')
  ph=digest(plan);need(ph in commit_map,'selected plan missing from full physical trace')
  receipt=read(planpath.parent/'commit_receipt.json');need(receipt['actual_plan_sha256']==ph and receipt['reported_outcome']=='accepted','receipt differs')
  verified.append({'plan_path':str(planpath.relative_to(ROOT)),'plan_sha256':ph,'commit_time':commit_map[ph]['time'],'raw_assembly_chunks':chunks,'apply_call_id':sel['selection_binding']['call_id']})
need(len(verified)==len(commits)==len({x['plan_sha256'] for x in verified}),'incomplete/duplicate plan coverage')
root=read(ROOT/'artifacts/smt_fullfab_diagnostics/B_budget_extension_v15/root_completion.json');old=root['account']['B_lineage_cumulative']
need(cost['attempts']==old['attempts'] and cost['known_tokens']==old['reported_input_output_tokens'] and set(unknown)==set(old['unknown_completed']),'cost totals differ')
classical=[e for e in ledger if e.get('event') in ['solver_reserve','constructor_reserve'] and any(str(e.get('run_id','')).startswith(str(r)) for r in runs)]
need(not classical,'classical calls recorded for B');need(not native,'B native tool events')
report={'valid':True,'scope':'Every committed B plan reconstructed from raw model-authored assembly, pure delta compiled, explicit model apply bound to full trace. All lineage usage checked against raw CLI event summaries and ledger. This does not authenticate remote provider signatures or fresh-run reliability.','plans_verified':len(verified),'raw_calls_verified':len(bycall),'cost':dict(cost),'unknown_call_ids':unknown,'classical_calls':len(classical),'native_tool_call_ids':native,'initial_plan_prompt_action_replay_calls':79,'verified':verified,'source_sha256':refs}
(OUT/'B_authorship_recheck.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print({k:report[k] for k in ['valid','plans_verified','raw_calls_verified','cost','classical_calls']},flush=True)
