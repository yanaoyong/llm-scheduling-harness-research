import collections,hashlib,io,json,re,shutil,subprocess,tarfile,time,zlib
from pathlib import Path
BASE=Path(__file__).resolve().parents[1];PUB=BASE/'public';ROOT=BASE.parents[1];REPO=ROOT/'archive/20261012_public_release';DEST=REPO/'docs/updates/2026-10-17'
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()

def main():
 sel=json.loads((PUB/'selection.json').read_text());assert sel.get('compressed_harness_unique_objects')==95008
 objects={};zipped=set();sql=set()
 for line in (PUB/'inventory.jsonl').open():
  row=json.loads(line);h=row['sha256'];assert row['object']==h
  if h in objects:assert objects[h]==row['size']
  objects[h]=row['size']
  if row.get('content_encoding')=='zlib':zipped.add(h)
  if row['path'].endswith('.public.sql'):sql.add(h)
 patterns={
 'personal_home_path':re.compile(rb'/(?:Users|home)/[A-Za-z][A-Za-z0-9._-]+/'),
 'credential':re.compile(rb'(?<![A-Za-z0-9_-])(?:sk-(?:(?:proj|live|svcacct|ant-api\d*)-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{30,})'),
 'opaque_ciphertext':re.compile(rb'gAAAA[A-Za-z0-9_=-]{70,}'),
 'actual_reasoning_item':re.compile(rb'"(?:channel|type)"\s*:\s*"(?:analysis|reasoning|agent_reasoning|reasoning_summary|reasoning_summary_text)"'),
 'private_key':re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
 }
 failures=[];seen=0;last=time.monotonic()
 def scan(raw,identity):
  for k,p in patterns.items():
   if p.search(raw):failures.append({'object_or_path':identity,'category':k})
 for h,n in objects.items():
  path=PUB/'objects'/h;raw=path.read_bytes();assert len(raw)==n and hashlib.sha256(raw).hexdigest()==h
  if h in zipped:raw=zlib.decompress(raw)
  scan(raw,h)
  if h in sql:
   for blob in re.finditer(rb"(?i)\bX'([0-9a-f]+)'",raw):scan(bytes.fromhex(blob.group(1).decode()),h+':SQL-BLOB')
  seen+=1
  if time.monotonic()-last>30:print(json.dumps({'stage':'privacy','objects_checked':seen,'of':len(objects),'findings':len(failures)}),flush=True);last=time.monotonic()
 for p in DEST.rglob('*'):
  if p.is_file():scan(p.read_bytes(),str(p.relative_to(REPO)))
 review={'status':'passed' if not failures else 'failed','public_objects_checked':len(objects),'compressed_objects_decoded_for_scan':len(zipped),'sql_objects_with_blob_scan':len(sql),'findings':failures,'scope':'High-confidence patterns; values never printed. Visible conversation exports exclude internal reasoning. Automatic scanning is not a guarantee of identifying every possible private detail.'}
 save(PUB/'privacy_review.json',review)
 if failures:raise SystemExit('Privacy review requires inspection; only object hashes/categories are in the local report.')
 shutil.copy2(BASE/'scripts/followup_archive.py',PUB/'followup_archive.py')
 (PUB/'README.md').write_text('''# 2026-10-17 排程实验公开增量证据包\n\n来自已封存本地完整快照，覆盖上一归档之后的新增和修改科学文件。未修改旧文件沿用 evidence-20261013-v1；不是从空目录就能重建整个项目的完整包。\n\n运行 `python3 followup_archive.py verify --archive followup-evidence-20261017.cas.tar.zst --expected-sha256 <archive-checksum.sha256 中记录的值>` 核验。`restore --dest <不存在的新目录>` 只写出普通文件，不执行实验脚本、不导入 SQL、不应用删除清单。可加 `--prefix project/experiments/context_window_batch60_20261016/live_pilots/extended_three_group_deadline_completion_20261017/` 选择一段。\n\nHarness 压缩对象解压脱敏后重新以 zlib 保存，后缀 `.z.public.json.z`。读取时 `zlib.decompress(Path(path).read_bytes())` 得到 UTF-8 内容；文件名中的旧对象引用用于溯源，不再代表公开内容哈希。对应关系在 transformations.jsonl 和 inventory.jsonl。科学 SQLite 为 `.public.sql` 逻辑导出，逐表记录数与脱敏行值已回导核验。\n\n原始会话、运行守卫、Codex 运行状态、Git 元数据、凭据、环境缓存及二进制附件只保存在本地。公开变换后的字节不能用于验证旧签名或原始账本链。本次没有重新运行模型、求解器或实验。会话与阅读指南在仓库 docs/updates/2026-10-17。\n''')
 target=PUB/'followup-evidence-20261017.cas.tar.zst';assert not target.exists();started=time.time()
 meta=['inventory.jsonl','excluded.jsonl','selection.json','transformations.jsonl','deleted_since_baseline.json','sqlite_verification.json','privacy_review.json','README.md','followup_archive.py']
 with target.with_suffix('.partial').open('xb') as out,(BASE/'review/public_compression.log').open('w') as log:
  proc=subprocess.Popen(['/opt/miniconda3/bin/zstd','-q','-T2','-8','-c'],stdin=subprocess.PIPE,stdout=out,stderr=log)
  try:
   with tarfile.open(fileobj=proc.stdin,mode='w|',format=tarfile.PAX_FORMAT) as tar:
    for name in meta:tar.add(PUB/name,arcname='metadata/'+name,recursive=False)
    for h,n in sorted(objects.items()):
     p=PUB/'objects'/h;info=tarfile.TarInfo('objects/'+h);info.size=n;info.mode=0o444
     with p.open('rb') as f:tar.addfile(info,f)
   proc.stdin.close();assert proc.wait()==0
  except BaseException:proc.kill();proc.wait();raise
 target.with_suffix('.partial').rename(target)
 result={'status':'passed','archive':target.name,'archive_sha256':sha(target),'compressed_bytes':target.stat().st_size,'objects':len(objects),'logical_file_paths':sel['selected_files'],'elapsed_seconds':time.time()-started}
 save(PUB/'build_result.json',result);print(json.dumps(result),flush=True)
if __name__=='__main__':main()
