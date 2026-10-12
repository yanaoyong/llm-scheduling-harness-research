#!/usr/bin/env python3
"""Read-only capture of project sources and relevant persisted Codex records.

Writes only within this new archive. Original trees and Git indexes are untouched.
Private raw records retain original bytes; readable exports omit internal reasoning.
"""
import argparse, collections, datetime, hashlib, json, os, re, shutil, subprocess, tarfile
from pathlib import Path

ARCHIVE = Path(__file__).resolve().parents[1]
ROOT = ARCHIVE.parents[1]
PRIVATE = ARCHIVE / 'private'
SCOPE = json.loads((ARCHIVE/'manifests/archive_scope.json').read_text())
CUTOFF = SCOPE['created_at']
TITLES = {
 '01a12e07-fae5-70c2-ad30-c126f1f1b178':'分析 Codex 工厂数据排程的缺陷',
 '01a12f91-839a-7c20-966e-c689ec30391a':'检查 Codex 会话是否偏移',
 '01a129dc-8ced-7071-9f77-f1038e8df2f8':'修复 B 记忆超限与重复读页并恢复排程',
 '01a12393-b066-79e3-ad84-0ee36b45d691':'查看另一个 Codex 会话进度',
 '01a11fc6-3c70-7380-aadd-4a88dbd97d58':'推进 SMT2020 全厂排程实验',
 '01a11e71-9b95-76c1-97d9-db087c25bc4c':'Read Codex goal objective',
 '01a11bce-5043-7871-b0e3-cd5f4e9f2393':'完成半导体排程三方案对照实验',
 '01a11e71-36be-7c72-8e34-6e223f43fcb4':None,
}
SOURCE_NAMES = ['experiment_round1','experiment_round2_3datasets','inputs','m0.5_research',
 'research_harness_scheduling_20261012','research_harness_scheduling_20261012_round2',
 'summary.md','relocation.json','SMT2020_全厂排程_续作_goal_prompt.txt']

def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def dt(v): return datetime.datetime.fromisoformat(v.replace('Z','+00:00'))
def dump(p,v):
 p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def git(repo,*args):
 return subprocess.run(['git','-C',str(repo),*args],capture_output=True,
  env={**os.environ,'GIT_OPTIONAL_LOCKS':'0'},check=True).stdout
def strings(v):
 if isinstance(v,str):yield v
 elif isinstance(v,dict):
  for x in v.values():yield from strings(x)
 elif isinstance(v,list):
  for x in v:yield from strings(x)

def conversations():
 candidates=[]; skipped=[]
 legacy='__LOCAL_HOME__/Downloads/大模型训练营/myharness/reports/research-llm-intelligent-scheduling-20261008'
 for base in [Path.home()/'.codex/sessions',Path.home()/'.codex/archived_sessions']:
  if not base.exists():continue
  for p in sorted(base.rglob('*.jsonl')):
   try:
    with p.open('rb') as f: meta=json.loads(f.readline())
    m=meta.get('payload',{}); tid=m.get('id') or m.get('session_id'); cwd=m.get('cwd','')
    relevant=tid in TITLES or cwd==str(ROOT) or cwd.startswith(str(ROOT)+'/') or cwd.startswith(legacy)
    if not relevant:continue
    if dt(meta['timestamp'])>dt(CUTOFF):
     skipped.append({'thread_id':tid,'reason':'created_after_archive_cutoff','path':str(p)});continue
    candidates.append((p,meta))
   except (ValueError,KeyError,OSError):continue
 rows=[]; attachment_dirs=set(); tool_index=[]
 for p,meta in candidates:
  m=meta['payload'];tid=m.get('id') or m.get('session_id')
  out=PRIVATE/'conversations'/f'{tid}.jsonl';out.parent.mkdir(parents=True,exist_ok=True)
  visible=[]; counts=collections.Counter(); last=None; original_size=p.stat().st_size
  turn_id=None; raw_bytes=0; n=0; stopped=False; compacted=0
  with p.open('rb') as src,out.open('xb') as dst:
   for n,b in enumerate(src,1):
    try:v=json.loads(b)
    except ValueError:
     stopped=True;break
    if v.get('timestamp') and dt(v['timestamp'])>dt(CUTOFF):stopped=True;break
    dst.write(b);raw_bytes+=len(b);last=v.get('timestamp',last)
    pl=v.get('payload',{}); typ=v.get('type');counts[typ]+=1
    if typ=='turn_context':turn_id=pl.get('turn_id',turn_id)
    if typ=='compacted':compacted+=1
    if typ=='response_item' and pl.get('type')=='message' and pl.get('role') in ('user','assistant'):
     if pl.get('channel') in ('analysis','summary'):continue
     if pl.get('role')=='assistant' and pl.get('phase') not in (None,'commentary','final_answer','final'):continue
     text='\n'.join(c.get('text','') for c in pl.get('content',[]) if c.get('type') in ('input_text','output_text','text'))
     assets=[{k:c[k] for k in ('type','image_url') if k in c} for c in pl.get('content',[]) if c.get('type') not in ('input_text','output_text','text')]
     # Never inline binary data URLs into readable exports.
     for a in assets:
      if isinstance(a.get('image_url'),str) and a['image_url'].startswith('data:'):a['image_url']='[embedded in private original record]'
     if text or assets:visible.append({'thread_id':tid,'source_line':n,'timestamp':v.get('timestamp'),'turn_id':turn_id,'message_id':pl.get('id'),'role':pl['role'],'phase':pl.get('phase'),'text':text,'assets':assets})
    if typ=='response_item' and pl.get('type') in ('function_call','custom_tool_call','function_call_output','custom_tool_call_output'):
     tool_index.append({'thread_id':tid,'source_line':n,'timestamp':v.get('timestamp'),'turn_id':turn_id,'type':pl['type'],'name':pl.get('name'),'call_id':pl.get('call_id')})
    # Capture explicit Codex attachment directories referenced by the record.
    if typ in ('response_item','event_msg'):
     for s in strings(pl):
      for x in re.findall(r'__LOCAL_HOME__/\.codex/attachments/([0-9a-fA-F-]{36})',s):attachment_dirs.add(x)
  tr=ARCHIVE/'conversations/transcripts';tr.mkdir(parents=True,exist_ok=True)
  with (tr/f'{tid}.jsonl').open('x') as f:
   for v in visible:f.write(json.dumps(v,ensure_ascii=False)+'\n')
  title=TITLES.get(tid) or f'会话 {tid}'
  md=[f'# {title}',f'\n线程 `{tid}`。原始记录截止 {last}。可见消息导出，不包含内部推理；工具原文保存在 private 原始记录，索引见 tool-index.jsonl。\n']
  for v in visible:
   md += [f'## {v["role"]} · {v["timestamp"]} · 原记录 L{v["source_line"]}',v['text']]
   if v['assets']:md += [json.dumps(v['assets'],ensure_ascii=False)]
  (tr/f'{tid}.md').write_text('\n\n'.join(md)+'\n')
  rows.append({'thread_id':tid,'title':TITLES.get(tid),'classification':'known_root' if tid in TITLES else 'related_persisted_session','source_path':str(p),'source_cwd':m.get('cwd'),'source_kind':m.get('source'),'cli_version':m.get('cli_version'),'original_size_at_read':original_size,'captured_bytes':raw_bytes,'cutoff_applied':stopped,'last_record_timestamp':last,'compaction_markers':compacted,'record_counts':dict(counts),'visible_messages':len(visible),'raw_path':str(out.relative_to(ARCHIVE)),'raw_sha256':sha(out),'transcript_jsonl':f'conversations/transcripts/{tid}.jsonl','transcript_md':f'conversations/transcripts/{tid}.md'})
 attachments=[]
 for uid in sorted(attachment_dirs):
  src=Path.home()/'.codex/attachments'/uid;dest=PRIVATE/'attachments'/uid
  if src.is_dir():
   shutil.copytree(src,dest,symlinks=True)
   for p in sorted(dest.rglob('*')):
    if p.is_file() and not p.is_symlink():attachments.append({'source':str(src/p.relative_to(dest)),'archive_path':str(p.relative_to(ARCHIVE)),'bytes':p.stat().st_size,'sha256':sha(p)})
  else:attachments.append({'source':str(src),'missing':True})
 dump(ARCHIVE/'conversations/index.json',{'cutoff_utc':CUTOFF,'coverage':'persisted sessions matching project cwd or known root IDs and legacy project path; related research CLI evidence also preserved in original project backup','limits':['not a reconstruction of unavailable historical records','compaction replacement summaries and internal reasoning omitted from readable export; private originals preserved','only explicitly referenced Codex attachment directories captured here; other dependencies listed separately','current thread is a prefix snapshot; subsequent archival work is documented in review files'],'sessions':rows,'excluded_after_cutoff':skipped,'attachments':attachments})
 with (ARCHIVE/'conversations/tool-index.jsonl').open('x') as f:
  for v in tool_index:f.write(json.dumps(v,ensure_ascii=False)+'\n')
 print(json.dumps({'conversations':len(rows),'visible_messages':sum(r['visible_messages'] for r in rows),'raw_bytes':sum(r['captured_bytes'] for r in rows),'attachments':len(attachments)},ensure_ascii=False),flush=True)

def git_snapshots():
 rows=[]
 for name,repo in [('experiment_round2_3datasets',ROOT/'experiment_round2_3datasets'),('myharness',ROOT.parent/'myharness')]:
  d=PRIVATE/'git'/name;d.mkdir(parents=True,exist_ok=True)
  head=git(repo,'rev-parse','HEAD').decode().strip()
  status=git(repo,'status','--porcelain=v1','-z','--untracked-files=all')
  (d/'status-before.z').write_bytes(status)
  (d/'worktree.patch').write_bytes(git(repo,'diff','--binary','HEAD'))
  (d/'index.patch').write_bytes(git(repo,'diff','--cached','--binary'))
  # Only the experiment history is bundled: myharness is a separate broader project.
  bundle=None
  if name=='experiment_round2_3datasets':
   bundle=d/'history.bundle';git(repo,'bundle','create',str(bundle),'--all')
   verify=git(repo,'bundle','verify',str(bundle)).decode()
   (d/'bundle-verify.txt').write_text(verify)
  idx=repo/'.git/index'
  rows.append({'name':name,'source_path':str(repo),'head':head,'status_entries':len(status.split(b'\0'))-1,'status_before_path':str((d/'status-before.z').relative_to(ARCHIVE)),'status_sha256':sha(d/'status-before.z'),'index_sha256_before':sha(idx) if idx.exists() else None,'bundle':str(bundle.relative_to(ARCHIVE)) if bundle else None,'bundle_sha256':sha(bundle) if bundle else None,'policy':'experiment: complete source backup + Git bundle + dirty/index patches; myharness: relevant source snapshot + dependency manifest, broader repository not copied'})
 dump(ARCHIVE/'manifests/git_sources.json',rows)
 print(json.dumps({'git_sources':len(rows)}),flush=True)

def light_sources():
 rows=[]
 selections={
 ROOT/'experiment_round1':['src','scripts','tests','docs','configs','prompts','README.md','requirements.lock','requirements.txt','pyproject.toml'],
 ROOT/'experiment_round2_3datasets':['src','scripts','tests','docs','configs','prompts','README.md','requirements.lock','.gitignore'],
 ROOT.parent/'myharness':['plugins/harness-core/scripts/codex-workflow.mjs','plugins/harness-core/scripts/lib','plugins/harness-core/workflows/m05-web-research.js','plugins/harness-core/workflows/m05-web-research.README.md','plugins/harness-core/workflows/codex-workflow.README.md','tests/harness_tools/codex_workflow.test.mjs'],
 }
 for repo,names in selections.items():
  for name in names:
   src=repo/name
   if not src.exists():continue
   files=sorted(src.rglob('*')) if src.is_dir() else [src]
   for p in files:
    if not p.is_file() or p.is_symlink() or '__pycache__' in p.parts or p.suffix=='.pyc':continue
    rel=Path(repo.name)/p.relative_to(repo);dest=ARCHIVE/'source_snapshot'/rel
    dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
    rows.append({'source':str(p),'archive_path':str(dest.relative_to(ARCHIVE)),'bytes':p.stat().st_size,'sha256':sha(dest)})
 dump(ARCHIVE/'manifests/source_snapshot.json',rows)
 print(json.dumps({'light_source_files':len(rows)}),flush=True)

class HashReader:
 def __init__(self,f):self.f=f;self.h=hashlib.sha256();self.n=0
 def read(self,n=-1):
  b=self.f.read(n);self.h.update(b);self.n+=len(b);return b

def backup():
 target=PRIVATE/'project-originals.tar.gz';manifest=ARCHIVE/'manifests/project_files.jsonl'
 if target.exists() or manifest.exists():raise RuntimeError('Never overwrite an existing snapshot')
 total=0;count=0;symlinks=[];changed=[];started=now()
 with manifest.open('x') as mf, tarfile.open(str(target),'w|gz',compresslevel=1,format=tarfile.PAX_FORMAT,dereference=False) as tar:
  for name in SOURCE_NAMES:
   root=ROOT/name
   paths=[root]+sorted(root.rglob('*')) if root.is_dir() else [root]
   for p in paths:
    if not p.exists() and not p.is_symlink():continue
    rel=str(p.relative_to(ROOT));info=tar.gettarinfo(str(p),arcname=rel);st=p.lstat()
    row={'path':rel,'mode':st.st_mode,'mtime_ns':st.st_mtime_ns,'size':st.st_size,'type':'other'}
    if info.isfile():
     with p.open('rb') as f:
      reader=HashReader(f);tar.addfile(info,reader)
      row.update(type='file',sha256=reader.h.hexdigest(),size=reader.n)
     after=p.stat()
     if (st.st_size,st.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):changed.append(rel)
     total+=row['size'];count+=1
     if count%1000==0:print(json.dumps({'files':count,'bytes':total,'current_top':name}),flush=True)
    else:
     tar.addfile(info)
     if info.issym():
      resolved=p.resolve(strict=False);row.update(type='symlink',target=os.readlink(p),resolved_target=str(resolved),target_exists=p.exists(),external_to_project=not resolved.is_relative_to(ROOT));symlinks.append(row.copy())
     elif info.isdir():row['type']='directory'
    mf.write(json.dumps(row,ensure_ascii=False)+'\n')
  # Include this exact file manifest inside the tar without changing originals.
  mf.flush();tar.add(manifest,arcname='ARCHIVE_PROJECT_FILES.jsonl',recursive=False)
 dump(ARCHIVE/'manifests/backup.json',{'started_at':started,'completed_at':now(),'source_root':str(ROOT),'archive_file':str(target.relative_to(ARCHIVE)),'archive_bytes':target.stat().st_size,'archive_sha256':sha(target),'manifest_path':str(manifest.relative_to(ARCHIVE)),'manifest_sha256':sha(manifest),'regular_files':count,'uncompressed_bytes':total,'changed_while_reading':changed,'symlinks':symlinks,'storage_scope':'same local disk; independent off-device backup not created','includes':['all original top-level project entries listed in SOURCE_NAMES including ignored data, runs, nested .git, environments'],'excludes':['new archive directory itself','unrelated personal Codex configuration and credentials','external symlink targets, individually inventoried']})
 print(json.dumps({'backup_complete':not changed,'files':count,'source_bytes':total,'archive_bytes':target.stat().st_size,'changed_files':changed,'symlinks':len(symlinks)},ensure_ascii=False),flush=True)

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['conversations','git','sources','backup']);a=ap.parse_args()
 {'conversations':conversations,'git':git_snapshots,'sources':light_sources,'backup':backup}[a.stage]()
