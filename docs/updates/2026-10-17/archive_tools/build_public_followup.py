#!/usr/bin/env python3
"""Build a sanitized incremental public archive from a frozen private CAS package."""
import collections,datetime,hashlib,io,json,os,re,shutil,socket,sqlite3,subprocess,tarfile,tempfile,time
from pathlib import Path,PurePosixPath
BASE=Path(__file__).resolve().parents[1];ROOT=BASE.parents[1]; PUB=BASE/'public'; PRIVATE=BASE/'private'; REPO=ROOT/'archive/20261012_public_release'; DEST=REPO/'docs/updates/2026-10-17'
USER=Path.home().name;HOST=socket.gethostname().split('.')[0]
STATS=collections.Counter(); OMIT=object()
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
PATTERNS=[('opaque_ciphertext',re.compile(r'gAAAA[A-Za-z0-9_=-]{70,}'),'__OPAQUE_CIPHERTEXT_REMOVED__'),('api_key',re.compile(r'(?<![\w-])sk-(?:(?:proj|live|svcacct|ant-api\d*)-)?[A-Za-z0-9_-]{20,}'),'__CREDENTIAL_REMOVED__'),('github_token',re.compile(r'\bgh[pousr]_[A-Za-z0-9_]{20,}\b'),'__CREDENTIAL_REMOVED__'),('github_fine_token',re.compile(r'\bgithub_pat_[A-Za-z0-9_]{30,}\b'),'__CREDENTIAL_REMOVED__'),('bearer',re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{20,}'),'Bearer __CREDENTIAL_REMOVED__'),('jwt',re.compile(r'\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}'),'__TOKEN_REMOVED__'),('private_key',re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',re.S),'__PRIVATE_KEY_REMOVED__')]
def sanitize_text(s):
 for old,new in [(str(ROOT),'__PROJECT_ROOT__'),(str(Path.home()),'__HOME__'),(HOST,'__HOST__')]:
  if old and old in s:STATS['local_identity']+=s.count(old);s=s.replace(old,new)
 s,n=re.subn(r'/(?:Users|home)/[^/\s\\\"<>]+','__HOME__',s);STATS['local_identity']+=n
 s,n=re.subn(r'(?i)%2f(?:users|home)%2f[^/%\s]+','__HOME__',s);STATS['local_identity']+=n
 for key,pat,repl in PATTERNS:s,n=pat.subn(repl,s);STATS[key]+=n
 # Remove mailbox identities while retaining explicitly public GitHub noreply metadata.
 s,n=re.subn(r'[A-Za-z0-9._%+-]+@(?:'+re.escape(HOST)+r'(?:\.local)?|[A-Za-z0-9.-]+\.[A-Za-z]{2,})',lambda m:m.group(0) if m.group(0).endswith(('users.noreply.github.com','noreply.github.com','noreply@anthropic.com')) else '__EMAIL__',s);STATS['email_matches']+=n
 return s
SECRET_KEYS={'access_token','refresh_token','id_token','api_key','openai_api_key','authorization','client_secret','encrypted_content'}
def clean(v,depth=0):
 if isinstance(v,dict):
  if v.get('channel') in ('analysis','summary') or v.get('type') in ('reasoning','agent_reasoning','reasoning_summary','reasoning_summary_text'):
   STATS['non_visible_reasoning']+=1;return {'publication_omitted':'non_user_facing_reasoning'}
  d={}
  for k,x in v.items():
   if k.lower() in SECRET_KEYS and x not in (None,'',False):d[k]='__PRIVATE_VALUE_REMOVED__';STATS['private_field']+=1
   else:d[sanitize_text(k)]=clean(x,depth+1)
  return d
 if isinstance(v,list):return [clean(x,depth+1) for x in v]
 if isinstance(v,str):
  st=v.strip()
  if depth<20 and st[:1] in ('{','[') and st[-1:] in ('}',']'):
   try:
    obj=json.loads(v);new=clean(obj,depth+1)
    if new!=obj:return json.dumps(new,ensure_ascii=False,separators=(',',':'))
   except (ValueError,RecursionError):pass
  return sanitize_text(v)
 return v

def transform(raw):
 try:
  enc='utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8'
  text=raw.decode(enc)
  if '\x00' in text:return None,'non_text_binary'
 except UnicodeError:return None,'non_text_binary'
 if re.search(r'(?m)^thinking\s*$',text):return None,'unstructured_model_reasoning_private_only'
 stripped=text.strip()
 if stripped[:1] in ('{','['):
  try:
   obj=json.loads(text);out=clean(obj)
   return (raw if out==obj else (json.dumps(out,ensure_ascii=False,separators=(',',':'))+'\n').encode(enc)),None
  except (ValueError,RecursionError):pass
 if '\n' in text and stripped.startswith('{'):
  lines=[]
  for line in text.splitlines(keepends=True):
   if not line.strip():lines.append(line);continue
   try:
    obj=json.loads(line);out=clean(obj);lines.append(line if out==obj else json.dumps(out,ensure_ascii=False,separators=(',',':'))+'\n')
   except (ValueError,RecursionError):lines.append(sanitize_text(line))
  return ''.join(lines).encode(enc),None
 return sanitize_text(text).encode(enc),None

def classify(path):
 p=PurePosixPath(path);parts=p.parts;name=p.name;low=path.lower()
 if any(x in parts for x in ('.git','.venv','venv','__pycache__','site-packages','.pytest_cache','.mypy_cache','.ruff_cache','.cache','wandb')):return 'rebuildable_runtime_cache_or_git_metadata'
 if any('codex-home' in x or 'codex_home' in x or x=='.codex' for x in parts):return 'codex_runtime_private_only'
 if ('model' in parts or any(x.startswith('attempt-') for x in parts)) and any(x in parts for x in ('state','sessions','archived_sessions','skills','tmp','shell_snapshots','memories')):return 'codex_runtime_private_only'
 if name in ('auth.json','credentials.json','.env','config.local.json') or name.startswith('.env.') or p.suffix.lower() in ('.pem','.key','.p12'):return 'credential_or_local_environment_private_only'
 if parts[0] in ('inputs','career_materials','career_application_report','application_plan'):return 'personal_inputs_or_career_assets_private_only'
 if p.suffix.lower() in ('.png','.jpg','.jpeg','.gif','.webp','.pdf','.docx','.pptx','.xlsx','.zip','.gz','.zst','.7z','.tar','.dylib','.so','.pyc','.pyo','.o','.a','.whl','.ttf','.woff','.woff2','.mp4','.pt','.pth') or name=='.DS_Store':return 'binary_attachment_or_rebuildable_artifact_private_only'
 if p.suffix in ('.sqlite','.sqlite3','.db') or name.endswith(('-wal','-shm')):return 'database_logical_export' if not name.endswith(('-wal','-shm')) else 'database_sidecar'
 return None

def git_selected(path,size):
 if size>4_000_000:return False
 ps=PurePosixPath(path).parts
 if ps[0]=='experiment_round2_3datasets':return len(ps)>=2 and (ps[1] in ('src','scripts','tests','configs','docs','prompts','progress') or len(ps)==2 and ps[1] in ('README.md','requirements.lock','pyproject.toml'))
 if ps[:2]==('experiments','context_window_batch60_20261016'):
  return len(ps)==3 and ps[2]=='README.md' or len(ps)>=4 and ps[2] in ('src','scripts','tests','configs') or len(ps)==4 and ps[2]=='reports' or len(ps)==5 and ps[2]=='live_pilots'
 if ps[0]=='analysis':return len(ps)<=3
 if ps[0]=='audit_ABC_1h_20261013':return len(ps)==2
 if ps[0] in ('research_harness_efficiency_20261016','research_harness_multiagent_20261016'):return len(ps)<=3 and PurePosixPath(path).suffix in ('.md','.json','.txt')
 return False

def put(raw):
 h=hashlib.sha256(raw).hexdigest();p=PUB/'objects'/h
 if not p.exists():p.write_bytes(raw)
 return h,len(raw)

def export_sql(dbpath):
 source=sqlite3.connect('file:'+str(dbpath)+'?mode=ro',uri=True)
 assert source.execute('PRAGMA quick_check').fetchone()[0]=='ok'
 tables=source.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
 indexes=source.execute("SELECT sql FROM sqlite_master WHERE type IN ('index','view','trigger') AND sql IS NOT NULL ORDER BY type,name").fetchall()
 path=dbpath.with_suffix('.public.sql'); counts={}; digests={}
 def ident(n):return '"'+n.replace('"','""')+'"'
 def value(v):
  if v is None:return 'NULL'
  if isinstance(v,(int,float)):return repr(v)
  if isinstance(v,bytes):
   out,_=transform(v)
   if out is None:raise ValueError('Opaque database BLOB retained privately')
   return "X'"+out.hex()+"'"
  return "'"+clean(v).replace("'","''")+"'"
 with path.open('w') as f:
  f.write('BEGIN TRANSACTION;\n')
  for name,ddl in tables:
   f.write(ddl+';\n');n=0;h=hashlib.sha256()
   for row in source.execute('SELECT * FROM '+ident(name)):
    line='INSERT INTO '+ident(name)+' VALUES('+','.join(value(v) for v in row)+');\n';f.write(line);h.update(line.encode());n+=1
   counts[name]=n;digests[name]=h.hexdigest()
  for (ddl,) in indexes:f.write(ddl+';\n')
  f.write('COMMIT;\n')
 source.close()
 # Validate syntax, row counts and the complete sanitized values on an independent temporary DB.
 restored=dbpath.with_suffix('.verify.sqlite3');target=sqlite3.connect(restored)
 target.executescript(path.read_text());assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 for name,n in counts.items():
  assert target.execute('SELECT count(*) FROM '+ident(name)).fetchone()[0]==n
  h=hashlib.sha256()
  for row in target.execute('SELECT * FROM '+ident(name)):
   # Already sanitized values must be unchanged by another transformation.
   line='INSERT INTO '+ident(name)+' VALUES('+','.join(value(v) for v in row)+');\n';h.update(line.encode())
  assert h.hexdigest()==digests[name],name
 target.close();restored.unlink()
 return path,{'tables':counts,'integrity_check':'ok','sanitized_row_values_verified':True}

def main():
 assert json.loads((BASE/'snapshot_result.json').read_text())['status']=='passed'
 PUB.mkdir(exist_ok=True);(PUB/'objects').mkdir(exist_ok=True);DEST.mkdir(parents=True,exist_ok=True)
 db=sqlite3.connect(BASE/'private/public_index.sqlite3');db.execute('CREATE TABLE entries(path TEXT PRIMARY KEY,hash TEXT,size INTEGER,mode INTEGER,mtime INTEGER,kind TEXT)');db.execute('CREATE INDEX byhash ON entries(hash)')
 old={}
 for line in (ROOT/'archive/20261012_project_archive/manifests/project_files.jsonl').open():
  r=json.loads(line)
  if r.get('type')=='file':old[r['path']]=r.get('sha256')
 unchanged=0;current=set();excluded=collections.Counter();excluded_bytes=collections.Counter();selected=0;dbpaths=[]
 ex=(PUB/'excluded.jsonl').open('w')
 for line in (PRIVATE/'project_inventory.jsonl').open():
  r=json.loads(line);path=r['path'];current.add(path)
  if r['type']!='file':continue
  if old.get(path)==r['sha256']:unchanged+=1;continue
  reason=classify(path)
  if reason and reason not in ('database_logical_export','database_sidecar'):
   excluded[reason]+=1;excluded_bytes[reason]+=r['size'];ex.write(json.dumps({'path':path,'reason':reason,'source_sha256':r['sha256'],'size':r['size']},ensure_ascii=False)+'\n');continue
  db.execute('INSERT INTO entries VALUES(?,?,?,?,?,?)',(path,r['sha256'],r['size'],r['mode'],r['mtime_ns'],reason or 'text'))
  selected+=1
  if reason=='database_logical_export':dbpaths.append(path)
 db.commit();save(PUB/'deleted_since_baseline.json',sorted(set(old)-current)); del current,old
 print(json.dumps({'stage':'public_selection','candidates':selected,'unchanged_in_previous_archive':unchanged,'database_paths':len(dbpaths),'excluded':dict(excluded)}),flush=True)
 needed={x[0] for x in db.execute('SELECT DISTINCT hash FROM entries')}; mappings={};sql_objects={};transformed=0;checked=0;last=time.monotonic();tmp=BASE/'private/database_copies';tmp.mkdir(exist_ok=True)
 with subprocess.Popen(['/opt/miniconda3/bin/zstd','-q','-d','-c',str(PRIVATE/'project.cas.tar.zst')],stdout=subprocess.PIPE) as proc:
  with tarfile.open(fileobj=proc.stdout,mode='r|') as tar:
   for member in tar:
    if not member.name.startswith('objects/'):continue
    h=member.name.split('/')[1]
    # Verify every private object, including objects not selected for public release.
    stream=tar.extractfile(member);check=hashlib.sha256();content=None
    if h in needed:
     if member.size>128*1024*1024:
      # Large scientific text handled line by line to keep memory bounded.
      temp=PUB/'objects'/('partial-'+h)
      with temp.open('wb') as out:
       for line in stream:
        check.update(line);b,reason=transform(line)
        if b is None:raise ValueError('Unexpected non-text large object '+h)
        out.write(b)
      ph=sha(temp);size=temp.stat().st_size;temp.rename(PUB/'objects'/ph);mappings[h]=(ph,size,None)
     else:
      content=stream.read();check.update(content)
      rows=db.execute('SELECT path,kind FROM entries WHERE hash=?',(h,)).fetchall()
      for path,kind in rows:
       if kind in ('database_logical_export','database_sidecar'):
        dst=tmp/path;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(content);sql_objects[path]=h
      if any(kind=='text' for _,kind in rows):
       if content.startswith(b'SQLite format 3\x00'):
        mappings[h]=(None,None,'unexpected_database_private_only')
       else:
        out,reason=transform(content)
        if out is not None:
         ph,size=put(out);mappings[h]=(ph,size,None);transformed+=ph!=h
        else:mappings[h]=(None,None,reason)
    else:
     for chunk in iter(lambda:stream.read(4*1024*1024),b''):check.update(chunk)
    assert check.hexdigest()==h,'Frozen object hash mismatch';checked+=1
    if time.monotonic()-last>30:
     print(json.dumps({'stage':'sanitize_and_verify','private_objects_verified':checked,'public_objects_transformed':transformed,'public_unique_files':len(mappings)}),flush=True);last=time.monotonic()
  assert proc.wait()==0
 sql_results=[];sql_cache={}
 for path in dbpaths:
  h=sql_objects[path];wal=tmp/(path+'-wal');wh=sha(wal) if wal.exists() else None;key=(h,wh)
  if key not in sql_cache:
   try:
    out,verification=export_sql(tmp/path);raw=out.read_bytes();ph,size=put(raw);sql_cache[key]=(ph,size,verification)
   except (sqlite3.DatabaseError,ValueError) as err:
    sql_cache[key]=(None,None,{'private_only_reason':type(err).__name__})
  ph,size,verification=sql_cache[key];mappings['sql:'+path]=(ph,size,None if ph else 'database_export_unavailable_private_original_retained')
  sql_results.append({'path':path,'public_path':path+'.public.sql','source_sha256':h,'source_wal_sha256':wh,'public_sha256':ph,**verification})
  if len(sql_results)%10==0:print(json.dumps({'stage':'sqlite_exports','paths':len(sql_results),'unique_exports':len(sql_cache)}),flush=True)
 inventory=(PUB/'inventory.jsonl').open('w');transformations=(PUB/'transformations.jsonl').open('w');gitfiles=[];n=0;total=0;public_hashes=set()
 for path,h,size,mode,mtime,kind in db.execute('SELECT * FROM entries ORDER BY path'):
  if kind=='database_sidecar':continue
  ph,ps,reason=mappings['sql:'+path if kind=='database_logical_export' else h]
  if reason:
   excluded[reason]+=1;excluded_bytes[reason]+=size;ex.write(json.dumps({'path':path,'reason':reason,'source_sha256':h,'size':size},ensure_ascii=False)+'\n');continue
  pubpath=path+'.public.sql' if kind=='database_logical_export' else path
  row={'path':'project/'+pubpath,'type':'file','mode':mode,'mtime_ns':mtime,'size':ps,'sha256':ph,'object':ph}
  inventory.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n');n+=1;total+=ps;public_hashes.add(ph)
  transformations.write(json.dumps({'path':pubpath,'source_sha256':h,'public_sha256':ph,'changed':h!=ph},ensure_ascii=False)+'\n')
  if kind=='text' and git_selected(path,ps):
   dest=DEST/'project'/path;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(PUB/'objects'/ph,dest);gitfiles.append({'path':str(dest.relative_to(REPO)),'source_sha256':h,'public_sha256':ph,'bytes':ps})
 for stream in [inventory,transformations,ex]:stream.close()
 save(PUB/'sqlite_verification.json',sql_results);save(BASE/'public_git_files.json',gitfiles)
 result={'schema':'followup-public-increment-v1','date':'2026-10-17','baseline_public_commit':'3c20c92f06796313d392fcc74668e78d4f4b7211','baseline_private_cutoff':'2026-10-12T12:48:19.877397+00:00','conversation_cutoff_utc':'2026-10-17T06:02:18+00:00','private_source_archive_sha256':json.loads((BASE/'snapshot_result.json').read_text())['archive_sha256'],'unchanged_source_paths_in_prior_archive':unchanged,'selected_files':n,'logical_public_bytes':total,'unique_public_objects':len(public_hashes),'unique_public_bytes':sum((PUB/'objects'/h).stat().st_size for h in public_hashes),'git_snapshot_files':len(gitfiles),'private_objects_verified':checked,'excluded_categories':{k:{'files':excluded[k],'bytes':excluded_bytes[k]} for k in excluded},'transformations':dict(STATS),'database_exports':len(sql_results),'database_exports_unavailable':sum(x.get('public_sha256') is None for x in sql_results),'limits':['Incremental public derivative; original complete snapshot remains private.','Unchanged paths stay in the prior archive; deletion list is historical data, never automatically applied.','Public transformations invalidate historical raw-byte signatures; no experiment was rerun.','Raw Codex runtime state, private conversations, credentials, caches and binary attachments are not public.']}
 save(PUB/'selection.json',result);save(BASE/'review/private_object_verification.json',{'status':'passed','objects_verified':checked,'archive_sha256':result['private_source_archive_sha256']});print(json.dumps({'stage':'public_complete',**result},ensure_ascii=False),flush=True)
 db.close()
if __name__=='__main__':main()
