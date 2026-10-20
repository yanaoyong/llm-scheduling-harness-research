#!/usr/bin/env python3
"""Capture scientific SQLite inputs, export verified SQL, and extend both packages.
CLI databases remain excluded. Only SQLite tables are restored in a private test DB.
"""
import argparse, datetime as dt, hashlib, io, json, os, shutil, sqlite3, tarfile
from pathlib import Path
from archive_stage import ROOT, DEST, sha, save, text, transform, add

def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def capture(output,s1):
 private=output/'private';cap=json.loads((private/'capture.json').read_text())
 if (private/'capture-primary.json').exists():raise ValueError('Supplement already captured')
 shutil.copyfile(private/'capture.json',private/'capture-primary.json')
 start=dt.datetime.now(dt.timezone.utc);supp=[]
 inputs=[(s1/'stage-s1/fixture/sealed-36000'/n,'s1/stage-s1/fixture/sealed-36000/'+n) for n in ('G0.sqlite','contexts.sqlite')]
 inputs.append((ROOT/'docs/updates/2026-10-17/project/experiments/harness_v6_20261017/pytest.ini','source/v6/pytest.ini'))
 for source,name in inputs:
  size=source.stat().st_size;p=private/'snapshot'/name;p.parent.mkdir(parents=True,exist_ok=True)
  assert not p.exists()
  with source.open('rb') as src,p.open('xb') as dst:shutil.copyfileobj(src,dst,4*1024*1024)
  assert p.stat().st_size==size==source.stat().st_size
  row={'path':name,'bytes':size,'sha256':digest(p),'source_changed_after_inventory':False}
  cap['files'].append(row);supp.append({**row,'source_mtime_utc':dt.datetime.fromtimestamp(source.stat().st_mtime,dt.timezone.utc).isoformat()})
  print('supplement captured',name,flush=True)
 removed=[e for e in cap['files'] if {'.pytest_cache','.hypothesis'}.intersection(Path(e['path']).parts)]
 cap['files']=[e for e in cap['files'] if e not in removed]
 names={e['path'] for e in supp};cap['excluded']=[e for e in cap['excluded'] if e['path'] not in names]
 cap['excluded'] += [{'path':e['path'],'reason':'rebuildable_cache','source_sha256':e['sha256'],'bytes':e['bytes']} for e in removed]
 cap['conversation_cutoff_utc']=cap['cutoff_utc'];cap['primary_inventory_cutoff_utc']=cap['cutoff_utc'];cap['cutoff_utc']=start.isoformat();cap['cutoff_beijing']=start.astimezone(dt.timezone(dt.timedelta(hours=8))).isoformat()
 cap['capture_finished_utc']=dt.datetime.now(dt.timezone.utc).isoformat();cap['semantics']+=' Scientific SQLite inputs and pytest configuration were captured in a later, separately recorded supplement; conversation prefixes retain the primary cutoff.'
 save(private/'capture.json',cap)
 save(DEST/'verification/supplement.json',{'capture_started_utc':start.isoformat(),'capture_finished_utc':cap['capture_finished_utc'],'primary_capture_sha256':digest(private/'capture-primary.json'),'files':supp,'removed_caches':[e['path'] for e in removed],'reason':'Scientific G0/context databases are evidence, unlike CLI state databases. pytest.ini is source configuration.'})

def ident(n):return '"'+n.replace('"','""')+'"'
def literal(v):
 if v is None:return 'NULL'
 if isinstance(v,(int,float)):return repr(v)
 if isinstance(v,bytes):return "X'"+v.hex()+"'"
 return "'"+v.replace("'","''")+"'"
def sanitized(v):
 if isinstance(v,(str,bytes)):
  public,reason=transform(v.encode() if isinstance(v,str) else v)
  if reason:raise ValueError('Non-text scientific database field: '+reason)
  return public.decode() if isinstance(v,str) else public
 return v

def export_database(dbpath,sqlpath):
 if sqlpath.exists():
  check=json.loads(sqlpath.with_suffix('.verified.json').read_text())
  assert digest(sqlpath)==check['sql_sha256'] and digest(dbpath)==check['source_sha256']
  return check
 source=sqlite3.connect('file:'+str(dbpath)+'?mode=ro&immutable=1',uri=True)
 assert source.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 schema=source.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
 assert not source.execute("SELECT name FROM sqlite_master WHERE type IN ('trigger','view')").fetchall()
 indexes=source.execute("SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL ORDER BY name").fetchall()
 counts={};hashes={};sqlpath.parent.mkdir(parents=True,exist_ok=True)
 with sqlpath.open('w') as out:
  out.write('BEGIN TRANSACTION;\n')
  for name,ddl in schema:
   assert ddl.startswith('CREATE TABLE') and ';' not in ddl
   out.write(ddl+';\n');n=0;h=hashlib.sha256()
   for row in source.execute('SELECT * FROM '+ident(name)):
    row=tuple(sanitized(v) for v in row);line='INSERT INTO '+ident(name)+' VALUES('+','.join(literal(v) for v in row)+');\n';out.write(line);h.update(line.encode());n+=1
    if (name=='contexts' and n%10==0) or n%1000==0:print('SQL rows',dbpath.name,name,n,flush=True)
   counts[name]=n;hashes[name]=h.hexdigest()
  for (ddl,) in indexes:
   assert ddl.startswith(('CREATE INDEX','CREATE UNIQUE INDEX')) and ';' not in ddl
   out.write(ddl+';\n')
  out.write('COMMIT;\n')
 source.close()
 restored=sqlpath.with_suffix('.verify.sqlite');target=sqlite3.connect(restored)
 # Execute complete statements incrementally; large payloads need not coexist in memory.
 fragments=[]
 with sqlpath.open() as inp:
  for line in inp:
   fragments.append(line)
   if line.rstrip().endswith(';'):
    statement=''.join(fragments)
    if sqlite3.complete_statement(statement):target.execute(statement);fragments=[]
 assert not fragments;assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 for name,n in counts.items():
  assert target.execute('SELECT count(*) FROM '+ident(name)).fetchone()[0]==n;h=hashlib.sha256()
  for row in target.execute('SELECT * FROM '+ident(name)):
   h.update(('INSERT INTO '+ident(name)+' VALUES('+','.join(literal(v) for v in row)+');\n').encode())
  assert h.hexdigest()==hashes[name],name
 target.close();restored.unlink()
 result={'tables':counts,'sanitized_row_hashes':hashes,'integrity_check':'ok','restored_rows_identical':True,'sql_sha256':digest(sqlpath),'sql_bytes':sqlpath.stat().st_size,'source_sha256':digest(dbpath)}
 save(sqlpath.with_suffix('.verified.json'),result)
 return result

def repack(path,manifest,extra,remove,excluded=None):
 temp=path.with_name(path.name+'.next')
 with tarfile.open(temp,'w:gz',compresslevel=1) as out,tarfile.open(path,'r|gz') as old:
  for member in old:
   if member.name in ('manifest.json','excluded.jsonl') or member.name in remove or member.name in extra:continue
   assert member.isfile();out.addfile(member,old.extractfile(member))
  for name,p in sorted(extra.items()):
   info=tarfile.TarInfo(name);info.size=p.stat().st_size;info.mode=0o644;info.mtime=0
   with p.open('rb') as f:out.addfile(info,f)
  add(out,'manifest.json',json.dumps(manifest,ensure_ascii=False).encode())
  if excluded is not None:add(out,'excluded.jsonl',excluded)
 os.replace(temp,path)

def build(output):
 private=output/'private';release=output/'release';cap=json.loads((private/'capture.json').read_text());supp=json.loads((DEST/'verification/supplement.json').read_text());public_manifest=json.loads((release/'manifest.json').read_text());private_manifest=json.loads((private/'manifest.json').read_text())
 extras={};originals={};rows=[];db_checks=[]
 for e in supp['files']:
  source=private/'snapshot'/e['path'];originals[e['path']]=source
  if source.suffix=='.sqlite':
   name=e['path']+'.public.sql';p=private/'public-supplement'/name
   check=export_database(source,p);db_checks.append({'source_path':e['path'],**check})
  else:
   name=e['path'];p=private/'public-supplement'/name;p.parent.mkdir(parents=True,exist_ok=True);b,reason=transform(source.read_bytes());assert reason is None;p.write_bytes(b)
  extras[name]=p;rows.append({'path':name,'source_path':e['path'],'source_sha256':e['sha256'],'sha256':digest(p),'bytes':p.stat().st_size,'transformed':name!=e['path'] or digest(p)!=e['sha256']})
 remove=set(supp['removed_caches']);extra_names={e['path'] for e in supp['files']}
 excluded=[json.loads(l) for l in (DEST/'evidence/excluded.jsonl').read_text().splitlines()]
 excluded=[e for e in excluded if e['path'] not in extra_names|remove]+[e for e in cap['excluded'] if e['path'] in remove]
 ex=''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in excluded).encode()
 public_manifest['files']=[e for e in public_manifest['files'] if e['path'] not in remove|set(extras)]+rows
 public_manifest['cutoff_utc']=cap['cutoff_utc'];public_manifest['conversation_cutoff_utc']=cap['conversation_cutoff_utc']
 private_manifest['files']=cap['files'];private_manifest.pop('archive_sha256',None)
 repack(release/'harness-v6-s1-public.tar.gz',public_manifest,extras,remove,ex)
 repack(private/'harness-v6-s1-original-selected.tar.gz',private_manifest,originals,remove)
 private_manifest['archive_sha256']=digest(private/'harness-v6-s1-original-selected.tar.gz');save(private/'manifest.json',private_manifest);save(release/'manifest.json',public_manifest)
 (DEST/'evidence/excluded.jsonl').write_bytes(ex)
 build=json.loads((DEST/'verification/archive-build.json').read_text())
 build.update({'files':len(public_manifest['files']),'logical_bytes':sum(e['bytes'] for e in public_manifest['files']),'archive_bytes':(release/'harness-v6-s1-public.tar.gz').stat().st_size,'archive_sha256':digest(release/'harness-v6-s1-public.tar.gz'),'private_files':len(cap['files']),'private_bytes':(private/'harness-v6-s1-original-selected.tar.gz').stat().st_size,'private_sha256':private_manifest['archive_sha256'],'scientific_sqlite_exports':len(db_checks)})
 from collections import Counter
 build['excluded']=dict(Counter(e['reason'] for e in excluded));save(DEST/'verification/archive-build.json',build);save(release/'archive-build.json',build)
 save(DEST/'verification/sqlite-exports.json',{'passed':True,'databases':db_checks})
 save(DEST/'verification/capture.json',{k:v for k,v in cap.items() if k not in ('files','sessions','excluded')})
 print('supplement repacked and SQL restored/verified',flush=True)
def export(output):
 private=output/'private';supp=json.loads((DEST/'verification/supplement.json').read_text())
 for e in supp['files']:
  if e['path'].endswith('.sqlite'):
   export_database(private/'snapshot'/e['path'],private/'public-supplement'/(e['path']+'.public.sql'))
 print('scientific SQL exports verified',flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('command',choices=['capture','export','build']);p.add_argument('--output',type=Path,required=True);p.add_argument('--s1',type=Path);a=p.parse_args();capture(a.output,a.s1) if a.command=='capture' else globals()[a.command](a.output)
