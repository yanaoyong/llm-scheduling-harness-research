#!/usr/bin/env python3
"""Verify or restore frozen follow-up CAS evidence without running experiments."""
import argparse,hashlib,json,os,re,shutil,sqlite3,subprocess,tarfile,tempfile,time
from pathlib import Path,PurePosixPath

def safe(name):
 p=PurePosixPath(name)
 if not name or p.is_absolute() or '..' in p.parts or str(p)!=name:raise ValueError('Unsafe archive path')
 return p

def digest(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()

def members(path):
 exe=shutil.which('zstd')
 if not exe:raise RuntimeError('Install zstd and make it available on PATH')
 proc=subprocess.Popen([exe,'-q','-d','-c',str(path)],stdout=subprocess.PIPE)
 try:
  with tarfile.open(fileobj=proc.stdout,mode='r|') as tar:
   for m in tar:
    safe(m.name)
    if not m.isfile():raise ValueError('CAS members must be regular files')
    yield m,tar.extractfile(m)
  if proc.wait():raise RuntimeError('zstd decompression failed')
 finally:
  if proc.poll() is None:proc.kill();proc.wait()

def run(args):
 archive=Path(args.archive);checksum=digest(archive)
 if args.expected_sha256 and checksum!=args.expected_sha256:raise ValueError('Package checksum mismatch')
 with tempfile.TemporaryDirectory(prefix='followup-verify-') as scratch:
  tmp=Path(scratch);db=sqlite3.connect(tmp/'index.sqlite3')
  db.execute('CREATE TABLE objects(hash TEXT PRIMARY KEY,size INTEGER)');db.execute('CREATE TABLE files(path TEXT PRIMARY KEY,hash TEXT,size INTEGER,mode INTEGER,mtime INTEGER)');db.execute('CREATE INDEX filehash ON files(hash)')
  count=0;size=0;metadata=set();skipped=0;last=time.monotonic()
  for m,stream in members(archive):
   if m.name.startswith('objects/'):
    h=m.name.split('/')[1]
    if not re.fullmatch('[0-9a-f]{64}',h):raise ValueError('Invalid object name')
    check=hashlib.sha256();n=0
    for b in iter(lambda:stream.read(4*1024*1024),b''):check.update(b);n+=len(b)
    if n!=m.size or check.hexdigest()!=h:raise ValueError('Object checksum mismatch')
    db.execute('INSERT INTO objects VALUES(?,?)',(h,n));count+=1;size+=n
   elif m.name in ('metadata/inventory.jsonl','metadata/project_inventory.jsonl'):
    if 'inventory' in metadata:raise ValueError('Multiple inventories')
    metadata.add('inventory')
    for line in stream:
     row=json.loads(line);safe(row['path'])
     if row['type']=='file':
      if row.get('object',row['sha256'])!=row['sha256']:raise ValueError('Object identity mismatch')
      db.execute('INSERT INTO files VALUES(?,?,?,?,?)',(row['path'],row['sha256'],row['size'],row['mode'],row['mtime_ns']))
     else:skipped+=1
   elif m.name.startswith('metadata/'):
    if m.name in metadata:raise ValueError('Duplicate metadata')
    metadata.add(m.name)
   else:raise ValueError('Unknown package namespace')
   if time.monotonic()-last>30:
    print(json.dumps({'stage':'verify','objects':count,'bytes':size}),flush=True);last=time.monotonic()
  db.commit()
  if 'inventory' not in metadata:raise ValueError('No inventory')
  missing=db.execute('SELECT COUNT(*) FROM files f LEFT JOIN objects o ON o.hash=f.hash WHERE o.hash IS NULL OR o.size!=f.size').fetchone()[0]
  if missing:raise ValueError('Missing or mismatched referenced objects')
  unreferenced=db.execute('SELECT COUNT(*) FROM objects o LEFT JOIN files f ON f.hash=o.hash WHERE f.hash IS NULL').fetchone()[0]
  if unreferenced:raise ValueError('Unreferenced objects')
  restored=0
  if args.command=='restore':
   dest=Path(args.dest)
   if dest.exists():raise ValueError('Restore destination must not exist')
   prefix=args.prefix or ''
   wanted={h for h, in db.execute('SELECT DISTINCT hash FROM files WHERE substr(path,1,?)=?',(len(prefix),prefix))}
   if not wanted:raise ValueError('Prefix selects no files')
   objdir=tmp/'objects';objdir.mkdir();dest.mkdir(parents=True)
   for m,stream in members(archive):
    if m.name.startswith('objects/') and m.name.split('/')[1] in wanted:
     h=m.name.split('/')[1]
     with (objdir/h).open('xb') as f:shutil.copyfileobj(stream,f,4*1024*1024)
   for path,h,n,mode,mtime in db.execute('SELECT * FROM files WHERE substr(path,1,?)=? ORDER BY path',(len(prefix),prefix)):
    out=dest/path;out.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(objdir/h,out);os.chmod(out,mode);os.utime(out,ns=(mtime,mtime))
    if digest(out)!=h:raise ValueError('Restored file mismatch')
    restored+=1
  result={'status':'passed','archive_sha256':checksum,'objects_verified':count,'unique_bytes':size,'file_paths':db.execute('SELECT count(*) FROM files').fetchone()[0],'nonfile_inventory_records':skipped,'restored_files':restored,'scope':'Regular-file bytes, hashes, modes and modification times; symlinks and directories recorded in private inventory are not materialized. No scripts, models, solvers or SQL are executed.'}
  if args.report:Path(args.report).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
  print(json.dumps(result),flush=True)

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['verify','restore']);p.add_argument('--archive',required=True);p.add_argument('--expected-sha256');p.add_argument('--dest');p.add_argument('--prefix');p.add_argument('--report');a=p.parse_args()
 if a.command=='restore' and not a.dest:p.error('restore requires --dest')
 run(a)
if __name__=='__main__':main()
