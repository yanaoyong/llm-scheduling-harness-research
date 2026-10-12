#!/usr/bin/env python3
"""Exactly one real CLI attempt; grants must already exist. --resume is offline."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.agents.model_transport import call_model

PROMPT = 'Transport probe only. Return status="ok" and native_tools_used=false. Do not invoke any native tool or schedule anything.'
SCHEMA = {'type':'object','properties':{'status':{'type':'string','enum':['ok']},'native_tools_used':{'type':'boolean','enum':[False]}},'required':['status','native_tools_used'],'additionalProperties':False}
if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--run-dir',required=True)
    p.add_argument('--grant-id',default='channel-probe-v1')
    p.add_argument('--resume',action='store_true')
    a = p.parse_args()
    cfg = json.loads((ROOT/'configs/model.json').read_text())
    cfg.update(grant_id=a.grant_id,timeout_seconds=180)
    r = call_model(PROMPT,SCHEMA,Path(a.run_dir),cfg,resume=a.resume)
    print(json.dumps({k:r[k] for k in ('call_id','status','failure_reason','duration_seconds','usage','completed_turns','native_tool_events')},ensure_ascii=False,indent=2))
    sys.exit(0 if r['status']=='success' else 1)
