"""Single authorized handshake, with immutable request identity and zero scheduling."""
import argparse
import json
import hashlib
from pathlib import Path
from .budget import ROOT,DEFAULT_LEDGER,APPROVAL,BudgetLedger
from .model_transport import ModelConfig,call_model

def probe(*,resume=False):
    approval=json.loads(APPROVAL.read_text())
    cfg=ModelConfig(model=approval['model'],reasoning_effort=approval['reasoning_effort'],
                    timeout_seconds=approval['per_call_timeout_seconds'],ledger_path=str(DEFAULT_LEDGER),
                    phase='stage2_probe',grant_id=approval['budget_id'],
                    authorization_context={'purpose':'channel_probe','arm':None,'window_seconds':0})
    schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}
    out=ROOT/'runs/smt_fullfab_stage2/channel_probe_v1'
    if resume:
        # Verify the immutable original request schema/config, including older
        # transport dataclasses; never re-fingerprint with newly added defaults.
        request=json.loads((out/'request.json').read_text())
        prompt=(out/'prompt.txt').read_text();saved_schema=json.loads((out/'schema.json').read_text())
        expected=hashlib.sha256((prompt+'\n'+json.dumps(saved_schema,ensure_ascii=False,indent=2)+'\n'+'\n'+json.dumps(request['config'],sort_keys=True)).encode()).hexdigest()
        r=json.loads((out/'result.json').read_text())
        if expected!=r['request_fingerprint'] or expected!=request['request_fingerprint']:
            raise ValueError('saved handshake fingerprint mismatch')
    else:
        r=call_model('This is a bounded transport handshake. Do not use any native tools. Return {"ok":true}.',
                     schema,out,cfg)
    print(json.dumps({k:r[k] for k in ('status','failure_reason','cli_version','duration_seconds','usage','completed_turns','native_tool_events')}))
    print(json.dumps(BudgetLedger().summary()))
    return r

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--resume',action='store_true');a=p.parse_args()
    raise SystemExit(0 if probe(resume=a.resume)['status']=='success' else 1)
