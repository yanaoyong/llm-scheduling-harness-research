from pathlib import Path
import sys,tempfile,zlib,time,json
O=Path(__file__).resolve().parent;sys.path.insert(0,str(O/'workspace'))
from src.smt_fullfab.harness.contracts import *
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness import transport
from src.smt_fullfab.harness.context_ablation import VARIANTS,SCHEMA,flags
from src.smt_fullfab.harness.presentation import unpack
initial=strict_json(zlib.decompress((O/'singleton_2403__baseline.initial.json.z').read_bytes()));config=strict_json((O/'singleton_2403__baseline.config.json').read_bytes());fp=fingerprint();results=[];values=[]
with tempfile.TemporaryDirectory(prefix='B-context-integration-') as d:
 for variant in VARIANTS:
  r=Runtime.start_new(Path(d)/variant,config,experiment_id='offline-full-context-integration',initial=initial)
  r.manifest['admission']={'experiment_kind':SCHEMA,'case_id':'singleton_2403__'+variant};r.reader=None
  try:
   c=r.context();action={'tool':'read_entities','context_ref':c['context_ref'],'queries':[{'kind':'machines','cursor':c['catalogs']['machines']['first_cursor'],'count':512,'fields':['machine','family','available_at','currently_busy','current_setup','missing_field_for_test']}]}
   raw_result=r.record_output(action);assert raw_result['status']=='ok';values.append([e['value'] for e in raw_result['results'][0]['entities']]);assert values[-1]==values[0]
   def frame():
    p=transport.prompt(r);assert len(p)<=120000
    return p,strict_json(p[p.index('\n{')+1:])
   prompt1,f1=frame();assert 'same_context_fact_memory' not in f1
   feedback=unpack(f1['last_tool_feedback']);recovered=False
   if flags(r)[1]:
    assert feedback['offloaded'] and not feedback['inline_complete'];idx=r.store.get(r.store.read('public',feedback['locator_index_ref'])['object_ref']);assert idx['count']==512
    target=idx['locators'][400]
    result=r.record_output({'tool':'read_artifact','artifact_ref':feedback['original_ref'],'lookups':[{'path':target['path'],'fields':None}]})
    assert result['results'][0]['value']==raw_result['results'][0]['entities'][400]['value'];recovered=True
    _,fread=frame();assert 'same_context_fact_memory' not in fread
   elif flags(r)[0]:
    assert feedback['provenance_externalized'];assert [e['value'] for e in feedback['results'][0]['entities']]==values[0]
   r.record_output({'tool':'read_entities','context_ref':c['context_ref'],'queries':[{'kind':'machines','ids':['0'],'fields':['machine','family']}]})
   prompt2,f2=frame();assert 'same_context_fact_memory' in f2
   assert r.store.rows('commits')==[] and r.env.t==2403
   results.append({'variant':variant,'first_read_prompt_chars':len(prompt1),'second_entity_read_prompt_chars':len(prompt2),'first_read_memory_visible':False,'second_read_memory_visible':True,'offloaded_first_result':feedback.get('offloaded',False),'actual_recovery_verified':recovered,'same_exact_business_values':True,'zero_model_calls':r.usage()['actual_model_attempts']==0})
  finally:r.close()
proof={'all_pass':True,'fingerprint_sha256':fp['sha256'],'source_unchanged':fp==fingerprint(),'remote_model_calls':0,'results':results,'created_epoch':time.time()};(O/'integration_preflight.json').write_bytes(encode(proof));print(json.dumps(proof,ensure_ascii=False))
