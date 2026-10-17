"""Decode, sanitize and re-encode harness zlib objects; remove Codex runtime prefixes."""
import importlib.util,collections,hashlib,json,re,sqlite3,subprocess,tarfile,time,zlib,shutil
from pathlib import Path
BASE=Path(__file__).resolve().parents[1];PUB=BASE/'public';PRIVATE=BASE/'private'
spec=importlib.util.spec_from_file_location('public',BASE/'scripts/build_public_followup.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
original_text=m.sanitize_text
text_gate=re.compile(r'__HOME____HOME__ KEY|@|'+re.escape(m.HOST))
def fast_text(text):
 return original_text(text) if text_gate.search(text) else text
m.sanitize_text=fast_text
original_transform=m.transform
raw_gate=re.compile(rb'__HOME____HOME__ KEY|@|access_token|refresh_token|id_token|api_key|authorization|client_secret|encrypted_content|reasoning|analysis|summary|'+re.escape(m.HOST.encode()))
def fast_transform(raw):
 if not raw_gate.search(raw):
  try:
   text=raw.decode('utf-8')
   if '\x00' not in text:return raw,None
  except UnicodeError:pass
 return original_transform(raw)
m.transform=fast_transform

def main():
 before=json.loads((PUB/'selection.json').read_text());m.save(BASE/'review/public_preliminary_selection.json',before)
 runtime=set()
 for line in (PRIVATE/'project_inventory.jsonl').open():
  r=json.loads(line);p=Path(r['path'])
  if r['type']=='file' and re.fullmatch(r'(goals|logs|memories|queue|state)_\d+\.sqlite',p.name):runtime.add(str(p.parent)+'/')
 def isruntime(path):return any(parent+'/' in runtime for parent in map(str,Path(path).parents))
 db=sqlite3.connect(PRIVATE/'compressed_public_index.sqlite3');db.execute('CREATE TABLE IF NOT EXISTS compressed(path TEXT PRIMARY KEY, hash TEXT, size INTEGER)');db.execute('DELETE FROM compressed');db.execute('CREATE INDEX IF NOT EXISTS compressed_hash ON compressed(hash)')
 excludes=PUB/'excluded.pending.jsonl';reasons=collections.Counter();bytes_by=collections.Counter()
 with excludes.open('w') as ex:
  for line in (PUB/'excluded.jsonl').open():
   r=json.loads(line);path=r['path']
   if isruntime(path):r['reason']='codex_runtime_private_only'
   elif r['reason']=='non_text_binary' and path.endswith('.z'):
    db.execute('INSERT INTO compressed VALUES(?,?,?)',(path,r['source_sha256'],r['size']));continue
   ex.write(json.dumps(r,ensure_ascii=False)+'\n');reasons[r['reason']]+=1;bytes_by[r['reason']]+=r['size']
 db.commit();needed={h for h, in db.execute('SELECT DISTINCT hash FROM compressed')}; mapping={};decoded=0;last=time.monotonic()
 print(json.dumps({'stage':'compressed_objects','logical_paths':db.execute('SELECT count(*) FROM compressed').fetchone()[0],'unique_compressed_objects':len(needed),'runtime_prefixes':len(runtime)}),flush=True)
 with subprocess.Popen(['/opt/miniconda3/bin/zstd','-q','-d','-c',str(PRIVATE/'project.cas.tar.zst')],stdout=subprocess.PIPE) as proc:
  with tarfile.open(fileobj=proc.stdout,mode='r|') as tar:
   for member in tar:
    if not member.name.startswith('objects/'):continue
    h=member.name.split('/')[1]
    if h not in needed:continue
    compressed=tar.extractfile(member).read();assert hashlib.sha256(compressed).hexdigest()==h
    raw=zlib.decompress(compressed);source_decoded=hashlib.sha256(raw).hexdigest()
    for path, in db.execute('SELECT path FROM compressed WHERE hash=?',(h,)):
     stem=Path(path).stem
     if re.fullmatch('[0-9a-f]{64}',stem):assert stem==source_decoded,'Source object ref mismatch'
    out,reason=m.transform(raw)
    if out is None:raise ValueError('Harness object is not publishable text: '+h+' '+str(reason))
    public=zlib.compress(out,6);ph,size=m.put(public);mapping[h]=(ph,size,hashlib.sha256(out).hexdigest(),source_decoded);decoded+=1
    if time.monotonic()-last>30:print(json.dumps({'stage':'compressed_sanitization','objects':decoded,'of':len(needed)}),flush=True);last=time.monotonic()
  assert proc.wait()==0
 assert len(mapping)==len(needed)
 oldindex=sqlite3.connect(PRIVATE/'public_index.sqlite3');inventory=PUB/'inventory.pending.jsonl';trans=PUB/'transformations.pending.jsonl';n=0;total=0;hashes=set()
 with inventory.open('w') as inv,trans.open('w') as tr,excludes.open('a') as ex:
  for line in (PUB/'inventory.jsonl').open():
   r=json.loads(line);path=r['path'].removeprefix('project/');sourcepath=path.removesuffix('.public.sql')
   if isruntime(sourcepath):
    source=oldindex.execute('SELECT hash,size FROM entries WHERE path=?',(sourcepath,)).fetchone();ex.write(json.dumps({'path':sourcepath,'reason':'codex_runtime_private_only','source_sha256':source[0],'size':source[1]},ensure_ascii=False)+'\n');reasons['codex_runtime_private_only']+=1;bytes_by['codex_runtime_private_only']+=source[1];continue
   inv.write(line);n+=1;total+=r['size'];hashes.add(r['sha256'])
  for line in (PUB/'transformations.jsonl').open():
   r=json.loads(line)
   if not isruntime(r['path'].removesuffix('.public.sql')):tr.write(line)
  for path,h,original_size in db.execute('SELECT * FROM compressed ORDER BY path'):
   ph,size,decoded_hash,raw_decoded_hash=mapping[h];source=oldindex.execute('SELECT mode,mtime FROM entries WHERE path=?',(path,)).fetchone();pubpath=path+'.public.json.z'
   row={'path':'project/'+pubpath,'type':'file','mode':source[0],'mtime_ns':source[1],'size':size,'sha256':ph,'object':ph,'content_encoding':'zlib','decoded_public_sha256':decoded_hash,'source_object_ref':raw_decoded_hash}
   inv.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n');tr.write(json.dumps({'path':pubpath,'source_sha256':h,'public_sha256':ph,'source_decoded_sha256':raw_decoded_hash,'decoded_public_sha256':decoded_hash,'changed':h!=ph,'encoding':'zlib'},ensure_ascii=False)+'\n');n+=1;total+=size;hashes.add(ph)
 for pending,target in [(inventory,PUB/'inventory.jsonl'),(trans,PUB/'transformations.jsonl'),(excludes,PUB/'excluded.jsonl')]:pending.replace(target)
 sql=json.loads((PUB/'sqlite_verification.json').read_text());sql=[x for x in sql if not isruntime(x['path'])];m.save(PUB/'sqlite_verification.json',sql)
 assert not any(not x['public_sha256'] for x in sql),'A scientific database export needs investigation'
 before.update(selected_files=n,logical_public_bytes=total,unique_public_objects=len(hashes),unique_public_bytes=sum((PUB/'objects'/h).stat().st_size for h in hashes),excluded_categories={k:{'files':reasons[k],'bytes':bytes_by[k]} for k in reasons},database_exports=len(sql),database_exports_unavailable=0,compressed_harness_object_paths=db.execute('SELECT count(*) FROM compressed').fetchone()[0],compressed_harness_unique_objects=len(mapping),runtime_prefixes_excluded=len(runtime))
 before['transformations']=dict(collections.Counter(before['transformations'])+m.STATS)
 before['limits']+=['Harness compressed objects were decompressed, sanitized and re-compressed as .z.public.json.z; original object names are provenance only.','Database logical exports include copied WAL state where present; original Codex runtime databases are private-only.','Public file inventory excludes private symlink metadata; restore never follows original external symlinks.']
 m.save(PUB/'selection.json',before);m.save(BASE/'review/compressed_object_verification.json',{'status':'passed','unique_objects_decoded':len(mapping),'original_object_refs_verified':True,'public_decoded_checksums_recorded':True,'scientific_sqlite_exports_verified':len(sql),'runtime_prefixes_excluded':len(runtime)})
 print(json.dumps({'stage':'complete','selected_files':n,'unique_objects':len(hashes),'unique_bytes':before['unique_public_bytes'],'sql_exports':len(sql)}),flush=True)
if __name__=='__main__':main()
