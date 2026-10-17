"""Frozen-cycle stdio MCP endpoint. No Store access; one process per cycle."""
import argparse
from copy import deepcopy
import os
from pathlib import Path
import sys
import threading
from .contracts import encode, digest, strict_json
from .facts import FactReader, reconstruct
from .submit import Submitter

TOOLS = {
    'read_entities': {'type':'object','properties':{'kind':{'type':'string'}, 'ids':{'type':'array'}, 'cursor':{'type':['string','null']}, 'count':{'type':'integer'}, 'fields':{'type':'array'}, 'where':{'type':'array'}},'required':['kind']},
    'validate_plan': {'type':'object','properties':{'expected_state_version':{},'submission_id':{'type':'string'},'delta':{'type':'object'}},'required':['expected_state_version','submission_id','delta'],'additionalProperties':False},
    'submit_plan': {'type':'object','properties':{'expected_state_version':{},'submission_id':{'type':'string'},'delta':{'type':'object'}},'required':['expected_state_version','submission_id','delta'],'additionalProperties':False},
    'get_decision_snapshot': {'type':'object','properties':{},'additionalProperties':False},
}

class CycleServer:
    def __init__(self, input_dir, output_dir, *, physical_precheck=None, max_tool_calls=100):
        self.input_dir, self.output_dir = Path(input_dir), Path(output_dir)
        if self.input_dir.resolve() == self.output_dir.resolve():
            raise ValueError('input and output directories must differ')
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log = (self.output_dir/'mcp.jsonl').open('xb')
        self.lock = threading.Lock()
        self.records=[]
        self.max_tool_calls=max_tool_calls
        payload=strict_json((self.input_dir/'cycle.json').read_bytes())
        self.snapshot=payload['snapshot']
        problem, base = reconstruct(payload['facts'])
        self.reader=FactReader(payload['context_ref'],payload['facts'])
        if payload.get('private_state'):
            from .factory_v6 import restore, prepare
            handle=(self.input_dir/payload['private_state']).resolve()
            if not handle.is_relative_to(self.input_dir.resolve()):
                raise ValueError('private state outside frozen input')
            physical=restore(strict_json(handle.read_bytes()), [])
            def physical_precheck(plan, problem, execution):
                try: prepare(physical,plan); return []
                except ValueError as exc: return [{'code':'physical_precheck','detail':str(exc)}]
        self.submitter=Submitter(base,problem,payload['execution_state'],physical_precheck=physical_precheck,**payload['submit_config'])

    def call(self, name, arguments):
        with self.lock:
            arguments=deepcopy(arguments)
            try:
                if len(self.records)>=self.max_tool_calls: raise ValueError('tool_budget')
                if name=='read_entities': result=self.reader.read(arguments)
                elif name=='get_decision_snapshot':
                    if arguments: raise ValueError('unexpected arguments')
                    result=deepcopy(self.snapshot)
                elif name in ('validate_plan','submit_plan'):
                    target=self.submitter if name=='submit_plan' else Submitter.restore(self.submitter.capture(),physical_precheck=self.submitter.physical_precheck)
                    result=target.submit_plan(**arguments)
                    if name=='submit_plan' and result['accepted'] and not (self.output_dir/'submission.json').exists():
                        value={'arguments':arguments,'plan':target.candidate,'receipt':result}
                        fd=os.open(self.output_dir/'submission.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                        with os.fdopen(fd,'wb') as f:
                            f.write(encode(value)); f.flush(); os.fsync(f.fileno())
                else: raise ValueError('unknown tool')
            except Exception as exc:
                result={'isError':True,'error':str(exc)}
            row={'seq':len(self.records), 'tool':name,'arguments':arguments,'arguments_sha256':digest(arguments),'result':result,'previous':self.records[-1]['sha256'] if self.records else None}
            row['sha256']=digest(row)
            self.log.write(encode(row)+b'\n');self.log.flush();os.fsync(self.log.fileno())
            self.records.append(row)
            return deepcopy(result)

    def rpc(self, request):
        identity=request.get('id')
        if request.get('jsonrpc')!='2.0': return {'jsonrpc':'2.0','id':identity,'error':{'code':-32600,'message':'Invalid Request'}}
        method=request.get('method')
        if method=='notifications/initialized': return None
        try:
            if method=='initialize': result={'protocolVersion':request.get('params',{}).get('protocolVersion','2024-11-05'),'capabilities':{'tools':{}},'serverInfo':{'name':'harness_v6','version':'1'}}
            elif method=='tools/list': result={'tools':[{'name':n,'description':n,'inputSchema':s} for n,s in TOOLS.items()]}
            elif method=='tools/call':
                p=request['params'];value=self.call(p['name'],p.get('arguments',{}))
                result={'content':[{'type':'text','text':encode(value).decode()}],'isError':bool(value.get('isError',False))}
            else: return {'jsonrpc':'2.0','id':identity,'error':{'code':-32601,'message':'Method not found'}}
            return {'jsonrpc':'2.0','id':identity,'result':result} if 'id' in request else None
        except (KeyError,TypeError,ValueError) as exc:
            return {'jsonrpc':'2.0','id':identity,'error':{'code':-32602,'message':str(exc)}}

    def close(self): self.log.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True);p.add_argument('--max-tool-calls',type=int,default=100)
    a=p.parse_args();server=CycleServer(a.input,a.output,max_tool_calls=a.max_tool_calls)
    try:
        for line in sys.stdin.buffer:
            try: response=server.rpc(strict_json(line))
            except (ValueError,TypeError,AttributeError): response={'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Parse error'}}
            if response is not None: sys.stdout.buffer.write(encode(response)+b'\n');sys.stdout.buffer.flush()
    finally: server.close()

if __name__=='__main__': main()
