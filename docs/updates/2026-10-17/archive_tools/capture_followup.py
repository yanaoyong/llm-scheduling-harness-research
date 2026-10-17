#!/usr/bin/env python3
"""Capture byte-preserving local evidence. Never run experiment code or models."""
import collections,datetime,hashlib,io,json,os,shutil,stat,subprocess,tarfile,time
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]; ROOT=BASE.parents[1]; PRIVATE=BASE/'private'
CUTOFF='2026-10-17T06:02:18+00:00'
OLD=ROOT/'archive/20261012_project_archive'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def save(p,v):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def dt(s):return datetime.datetime.fromisoformat(s.replace('Z','+00:00'))
def git(*args):return subprocess.check_output(['git','--no-optional-locks','-C',str(ROOT/'experiment_round2_3datasets'),*args],env={**os.environ,'GIT_OPTIONAL_LOCKS':'0'})
def main():
 PRIVATE.mkdir(parents=True,exist_ok=True)
 assert not (PRIVATE/'project.cas.tar.zst').exists()
 old_index=json.loads((OLD/'conversations/index.json').read_text()); oldcut=dt(old_index['cutoff_utc']); end=dt(CUTOFF)
 oldids={r['thread_id'] for r in old_index['sessions']}; sessions=[]; visible_dir=BASE/'conversations';visible_dir.mkdir(exist_ok=True)
 for b in [Path.home()/'.codex/sessions',Path.home()/'.codex/archived_sessions']:
  for p in sorted(b.rglob('*.jsonl')):
   try:
    with p.open('rb') as f:meta=json.loads(f.readline())
    m=meta.get('payload',{});tid=m.get('id');cwd=m.get('cwd','')
    if not tid or not (cwd==str(ROOT) or cwd.startswith(str(ROOT)+'/') or tid in oldids):continue
    if dt(meta['timestamp'])>end:continue
    if p.stat().st_mtime<oldcut.timestamp():continue
   except (OSError,ValueError,KeyError):continue
   raw=PRIVATE/'conversations'/f'{tid}.jsonl';raw.parent.mkdir(exist_ok=True)
   msgs=[];tools=[];post=0;last=None;count=0;turn=None;guardian=isinstance(m.get('source'),dict) and 'guardian' in json.dumps(m['source'])
   with p.open('rb') as src,raw.open('xb') as dst:
    for n,line in enumerate(src,1):
     try:v=json.loads(line)
     except ValueError:break
     stamp=v.get('timestamp')
     if stamp and dt(stamp)>end:break
     dst.write(line);count+=1;last=stamp or last
     if not stamp or dt(stamp)<=oldcut:continue
     post+=1;pl=v.get('payload',{});typ=v.get('type')
     if typ=='turn_context':turn=pl.get('turn_id',turn)
     if guardian:continue
     if typ=='response_item' and pl.get('type')=='message' and pl.get('role') in ('user','assistant') and pl.get('channel') not in ('analysis','summary'):
      text='\n'.join(c.get('text','') for c in pl.get('content',[]) if c.get('type') in ('input_text','output_text','text'))
      if text:msgs.append({'thread_id':tid,'source_line':n,'timestamp':stamp,'turn_id':turn,'role':pl['role'],'phase':pl.get('phase'),'text':text})
     elif typ=='response_item' and pl.get('type') in ('function_call','custom_tool_call','function_call_output','custom_tool_call_output'):
      tools.append({'source_line':n,'timestamp':stamp,'type':pl['type'],'name':pl.get('name'),'call_id':pl.get('call_id')})
   if not post:raw.unlink();continue
   (visible_dir/f'{tid}.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in msgs))
   (visible_dir/f'{tid}.tools.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in tools))
   sessions.append({'thread_id':tid,'source_kind':m.get('source'),'classification':'operational_guardian_private_only' if guardian else ('root' if isinstance(m.get('source'),str) else 'delegated_subagent'),'prior_archive_contains_thread':tid in oldids,'captured_records':count,'records_after_prior_cutoff':post,'visible_messages':len(msgs),'raw_bytes':raw.stat().st_size,'raw_sha256':sha(raw),'last_record_timestamp':last})
 save(BASE/'conversation_capture.json',{'prior_cutoff_utc':old_index['cutoff_utc'],'cutoff_utc':CUTOFF,'sessions':sessions,'raw_sessions':len(sessions),'visible_messages':sum(x['visible_messages'] for x in sessions),'raw_bytes':sum(x['raw_bytes'] for x in sessions),'limits':['Visible exports contain only messages after the previous cutoff. Private prefixes preserve original line numbers.','Operational guardian sessions remain private; they are not human decisions.','Current archive execution after cutoff is documented separately.']})
 print(json.dumps({'stage':'conversations','sessions':len(sessions),'messages':sum(x['visible_messages'] for x in sessions)}),flush=True)
 gd=PRIVATE/'git';gd.mkdir(exist_ok=True)
 for name,args in [('status-before.z',('status','--porcelain=v1','-z','--untracked-files=all')),('worktree.patch',('diff','--binary','HEAD')),('index.patch',('diff','--cached','--binary')),('log.txt',('log','--date=iso','--format=%H %ad %s'))]: (gd/name).write_bytes(git(*args))
 idx=ROOT/'experiment_round2_3datasets/.git/index'; before={'head':git('rev-parse','HEAD').decode().strip(),'index_sha256':sha(idx),'status_sha256':sha(gd/'status-before.z')}
 git('bundle','create',str(gd/'history.bundle'),'--all');save(BASE/'git_before.json',before)
 names=sorted(p.name for p in ROOT.iterdir() if p.name not in ('archive','.DS_Store'))
 save(BASE/'scope.json',{'cutoff_utc':CUTOFF,'snapshot_started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'included_top_level':names,'excluded_top_level':['archive (previous archives and this new destination)','.DS_Store'],'policy':'Full byte-preserving current project snapshot with SHA-256 content deduplication; no source deletion or mutation.'})
 target=PRIVATE/'project.cas.tar.zst'; manifest=PRIVATE/'project_inventory.jsonl'; seen={}; inode_cache={};count=0;total=0;unique_bytes=0;lastlog=time.monotonic();changed=[];topcounts=collections.defaultdict(lambda:[0,0]);started=time.time()
 with target.with_suffix('.partial').open('xb') as output,(BASE/'review/compression.log').open('w') as log,manifest.open('x') as mf:
  proc=subprocess.Popen(['/opt/miniconda3/bin/zstd','-q','-T2','-5','-c'],stdin=subprocess.PIPE,stdout=output,stderr=log)
  try:
   with tarfile.open(fileobj=proc.stdin,mode='w|',format=tarfile.PAX_FORMAT) as tar:
    for name in names:
     root=ROOT/name
     def paths():
      yield root
      if root.is_dir() and not root.is_symlink():
       for d,ds,fs in os.walk(root,followlinks=False):
        ds.sort();fs.sort()
        for dn in ds:yield Path(d)/dn
        for fn in fs:yield Path(d)/fn
     for p in paths():
      st=p.lstat();rel=str(p.relative_to(ROOT));row={'path':rel,'mode':stat.S_IMODE(st.st_mode),'mtime_ns':st.st_mtime_ns}
      if stat.S_ISLNK(st.st_mode):row.update(type='symlink',target=os.readlink(p))
      elif stat.S_ISDIR(st.st_mode):row.update(type='directory')
      elif stat.S_ISREG(st.st_mode):
       raw=None;ik=(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)
       if ik in inode_cache:h=inode_cache[ik]
       elif st.st_size<=8*1024*1024:
        raw=p.read_bytes();h=hashlib.sha256(raw).hexdigest();inode_cache[ik]=h
       else:h=sha(p);inode_cache[ik]=h
       row.update(type='file',size=st.st_size,sha256=h,object=h)
       if h not in seen:
        info=tarfile.TarInfo('objects/'+h);info.size=st.st_size;info.mode=0o444
        if raw is not None:tar.addfile(info,io.BytesIO(raw))
        else:
         with p.open('rb') as f:tar.addfile(info,f)
        seen[h]=st.st_size;unique_bytes+=st.st_size
       assert seen[h]==st.st_size
       after=p.stat()
       if (st.st_ino,st.st_size,st.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):changed.append(rel)
       count+=1;total+=st.st_size;topcounts[name][0]+=1;topcounts[name][1]+=st.st_size
      else:row.update(type='special_not_copied')
      mf.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')
      if time.monotonic()-lastlog>30:
       print(json.dumps({'stage':'snapshot','files':count,'logical_gb':round(total/1e9,3),'unique_gb':round(unique_bytes/1e9,3),'top':name}),flush=True);lastlog=time.monotonic()
    mf.flush();tar.add(manifest,arcname='metadata/project_inventory.jsonl',recursive=False)
    for fname in ['scope.json','conversation_capture.json','git_before.json']:tar.add(BASE/fname,arcname='metadata/'+fname,recursive=False)
   proc.stdin.close();assert proc.wait()==0
  except BaseException:
   proc.kill();proc.wait();raise
 target.with_suffix('.partial').rename(target)
 after={'head':git('rev-parse','HEAD').decode().strip(),'index_sha256':sha(idx),'status_sha256':hashlib.sha256(git('status','--porcelain=v1','-z','--untracked-files=all')).hexdigest()}
 result={'status':'passed' if not changed and before==after else 'failed','snapshot_completed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'files':count,'logical_bytes':total,'unique_objects':len(seen),'unique_bytes':unique_bytes,'compressed_bytes':target.stat().st_size,'archive_sha256':sha(target),'manifest_sha256':sha(manifest),'changed_while_reading':changed,'original_B_git_unchanged':before==after,'top_level_counts':dict(topcounts),'elapsed_seconds':time.time()-started}
 save(BASE/'snapshot_result.json',result);print(json.dumps(result,ensure_ascii=False),flush=True)
 if result['status']!='passed':raise SystemExit(1)
if __name__=='__main__':main()
