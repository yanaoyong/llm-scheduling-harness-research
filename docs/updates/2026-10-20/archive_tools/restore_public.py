#!/usr/bin/env python3
"""Verify every public member before extracting into a new directory."""
import argparse, hashlib, json, tarfile
from pathlib import Path, PurePosixPath

def restore(archive,dest):
 if dest.exists():raise ValueError('Destination already exists')
 actual={};seen=set()
 with tarfile.open(archive,'r:gz') as t:
  for m in t:
   p=PurePosixPath(m.name)
   if not m.isfile() or p.is_absolute() or '..' in p.parts or m.name in seen:raise ValueError('Unsafe archive member')
   seen.add(m.name);raw=t.extractfile(m).read()
   if m.name=='manifest.json':manifest=json.loads(raw)
   elif m.name!='excluded.jsonl':actual[m.name]={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
  expected={e['path']:{'sha256':e['sha256'],'bytes':e['bytes']} for e in manifest['files']}
  if actual!=expected:raise ValueError('Manifest mismatch')
  dest.mkdir(parents=True)
  for m in t.getmembers():
   p=dest/m.name;p.parent.mkdir(parents=True,exist_ok=True)
   with p.open('xb') as f:
    source=t.extractfile(m)
    for b in iter(lambda:source.read(4*1024*1024),b''):f.write(b)
 print(json.dumps({'verified_files':len(actual),'restored':len(seen)}))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True);p.add_argument('--dest',type=Path,required=True);a=p.parse_args();restore(a.archive,a.dest)
