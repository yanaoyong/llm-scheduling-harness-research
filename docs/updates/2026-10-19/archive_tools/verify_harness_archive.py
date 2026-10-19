#!/usr/bin/env python3
"""Verify public archive bytes and selected scientific claims; never execute runs."""
import argparse,hashlib,json,re,tarfile
from pathlib import Path,PurePosixPath

def verify(path,build_path):
 build=json.loads(build_path.read_text())
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
 assert h.hexdigest()==build['archive_sha256'],'archive checksum'
 with tarfile.open(path,'r:gz') as tar:
  members=tar.getmembers();names=[m.name for m in members]
  assert len(set(names))==len(names),'duplicate path'
  assert all(m.isfile() and not PurePosixPath(m.name).is_absolute() and '..' not in PurePosixPath(m.name).parts for m in members),'unsafe member'
  manifest=json.load(tar.extractfile('manifest.json'));records=manifest['files']
  assert set(names)=={r['path'] for r in records}|{'manifest.json'}
  privacy_patterns=[re.compile(x) for x in (
   r'/(?:Users|home)/[^/\s\\\"<>]+',
   r'(?<![\w-])sk-(?:(?:proj|live|svcacct|ant-api\d*)-)?[A-Za-z0-9_-]{20,}',
   r'\bgh[pousr]_[A-Za-z0-9_]{20,}\b',r'\bgithub_pat_[A-Za-z0-9_]{30,}\b',
   r'\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}',
   r'gAAAA[A-Za-z0-9_=-]{70,}')]
  for row in records:
   data=tar.extractfile(row['path']).read()
   assert len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==row['sha256'],row['path']
   text=data.decode('utf-8')
   assert not any(pattern.search(text) for pattern in privacy_patterns),'privacy scan: '+row['path']
  def read(name):return json.load(tar.extractfile('goal/'+name))
  status=read('GOAL_STATUS.json');qualification=read('qualification-stall-v1.json');failure=read('smoke-E1-stall-1-diagnosis.json')
  assert status['gates']['formal_trajectories']=='0/6'
  assert qualification['tests']==dict(passed=660,subtests=38,failed=0,skipped=0)
  assert failure['requests']==1 and len(failure['missing_task_references'])==9
  assert failure['usage']==dict(input_tokens=180968,cached_input_tokens=0,output_tokens=915)
  usage=status['real_model_requests'];assert usage['attempts_started']==55 and usage['known_completed_responses']==51 and usage['unknown_usage_failures']==4 and usage['pending_native_requests']==0
  # Independently sum every archived native completion, including excluded runs.
  totals=dict(input_tokens=0,cached_input_tokens=0,output_tokens=0);started=completed=failed=0
  for name in names:
   parts=PurePosixPath(name).parts
   if len(parts)!=4 or parts[0]!='goal' or not parts[1].endswith('-native-trace') or not parts[1].startswith(('ab-real-','smoke-','formal-')) or parts[-1]!='trace.jsonl':continue
   for line in tar.extractfile(name).read().splitlines():
    event=json.loads(line)['payload'];kind=event.get('type')
    if kind=='inference_started':started+=1
    if kind=='inference_failed':failed+=1
    if kind=='inference_completed':
     completed+=1;relative=str(PurePosixPath(name).parent/event['response_payload']['path'])
     tokens=json.load(tar.extractfile(relative))['token_usage']
     for key in totals:totals[key]+=tokens[key]
  assert (started,completed,failed)==(55,51,4)
  assert totals==usage['known_usage_totals']
 return dict(passed=True,files=len(records),native_attempts=started,known_responses=completed,unknown_usage_failures=failed,known_usage=totals,formal_complete='0/6',privacy_pattern_findings=0,model_calls=0)

if __name__=='__main__':
 p=argparse.ArgumentParser();base=Path(__file__).resolve().parents[1]
 p.add_argument('--archive',type=Path,required=True)
 p.add_argument('--build',type=Path,default=base/'verification/archive-build.json')
 p.add_argument('--output',type=Path)
 a=p.parse_args();result=verify(a.archive,a.build)
 if a.output:
  assert not a.output.exists();a.output.write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result))
