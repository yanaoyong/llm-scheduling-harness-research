#!/usr/bin/env python3
"""Verify archive bytes without invoking experiments, models or installation.

Default checks the tar and frozen exports. --check-originals additionally reads
the original source tree. --restore-smoke materializes selected regular files and
clones the saved Git history only in private/restore_smoke (never in originals).
"""
import argparse, collections, hashlib, json, os, subprocess, tarfile, datetime
from pathlib import Path, PurePosixPath

A=Path(__file__).resolve().parents[1]
def digest_stream(f):
 h=hashlib.sha256();n=0
 for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b);n+=len(b)
 return h.hexdigest(),n
def sha(p):
 with p.open('rb') as f:return digest_stream(f)[0]
def load(p):return json.loads(p.read_text())
def run(cmd):return subprocess.run(cmd,capture_output=True,check=True,env={**os.environ,'GIT_OPTIONAL_LOCKS':'0'}).stdout
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--check-originals',action='store_true');ap.add_argument('--restore-smoke',action='store_true');ap.add_argument('--output',default='review/archive_verification.json');args=ap.parse_args()
 errors=[]; checks={}; meta=load(A/'manifests/backup.json'); source=Path(meta['source_root'])
 manifest=A/meta['manifest_path'];rows={v['path']:v for v in map(json.loads,manifest.read_text().splitlines())}
 checks['manifest_sha256_matches']=sha(manifest)==meta['manifest_sha256']
 checks['tar_sha256_matches']=sha(A/meta['archive_file'])==meta['archive_sha256']
 seen=set();file_count=0;byte_count=0;smoke=[]
 samples={'summary.md','SMT2020_全厂排程_续作_goal_prompt.txt','experiment_round2_3datasets/requirements.lock','experiment_round2_3datasets/artifacts/final/acceptance.json','experiment_round2_3datasets/progress/smt_fullfab/ACTIVE_WORK.json','experiment_round2_3datasets/src/smt_fullfab/plan_delta.py','experiment_round2_3datasets/docs/smt_fullfab/B_1h_results_efficiency_and_next_budget_20261012.md','research_harness_scheduling_20261012_round2/m0.5_research/summary.md','research_harness_scheduling_20261012_round2/m0.5_research/evidence/completion.json'}
 with tarfile.open(str(A/meta['archive_file']),'r|gz') as tar:
  for member in tar:
   name=member.name
   if name=='ARCHIVE_PROJECT_FILES.jsonl':
    with tar.extractfile(member) as f:checks['embedded_manifest_matches']=digest_stream(f)[0]==meta['manifest_sha256']
    continue
   pp=PurePosixPath(name)
   if pp.is_absolute() or '..' in pp.parts:errors.append({'unsafe_tar_path':name});continue
   if name in seen:errors.append({'duplicate_tar_path':name})
   seen.add(name);row=rows.get(name)
   if row is None:errors.append({'unexpected_member':name});continue
   if row['type']=='file':
    if not member.isfile():errors.append({'wrong_type':name});continue
    with tar.extractfile(member) as f:
     if args.restore_smoke and name in samples:
      content=f.read();h=hashlib.sha256(content).hexdigest();n=len(content)
      dest=A/'private/restore_smoke/files'/name;dest.parent.mkdir(parents=True,exist_ok=True)
      if dest.exists():raise RuntimeError('restore smoke destination already exists: '+str(dest))
      dest.write_bytes(content);smoke.append({'path':name,'sha256_matches':sha(dest)==row['sha256']})
     else:h,n=digest_stream(f)
    if h!=row['sha256'] or n!=row['size']:errors.append({'tar_content_mismatch':name})
    file_count+=1;byte_count+=n
   elif row['type']=='symlink':
    if not member.issym() or member.linkname!=row['target']:errors.append({'symlink_mismatch':name})
   elif row['type']=='directory':
    if not member.isdir():errors.append({'directory_mismatch':name})
   else:errors.append({'unhandled_member_type':name,'tar_type':str(member.type)})
   if file_count and file_count%20000==0:print(json.dumps({'verified_tar_files':file_count,'bytes':byte_count}),flush=True)
 missing=set(rows)-seen
 if missing:errors.append({'missing_members':sorted(missing)})
 checks['tar_manifest_complete']=not missing and len(seen)==len(rows)
 checks['no_source_changes_during_capture']=not meta['changed_while_reading']
 conv=load(A/'conversations/index.json');message_count=0
 for s in conv['sessions']:
  raw=A/s['raw_path'];trs=[json.loads(x) for x in (A/s['transcript_jsonl']).read_text().splitlines()];by_line={v['source_line']:v for v in trs}
  if sha(raw)!=s['raw_sha256']:errors.append({'raw_conversation_hash':s['thread_id']})
  with raw.open() as f:
   for i,line in enumerate(f,1):
    if i not in by_line:continue
    v=json.loads(line);p=v['payload'];r=by_line.pop(i)
    text='\n'.join(c.get('text','') for c in p.get('content',[]) if c.get('type') in ('input_text','output_text','text'))
    if p.get('role')!=r['role'] or text!=r['text'] or v.get('timestamp')!=r['timestamp']:errors.append({'transcript_mismatch':s['thread_id'],'source_line':i})
    if p.get('type')!='message' or r['role'] not in ('user','assistant') or p.get('channel') in ('analysis','summary'):errors.append({'nonvisible_transcript_item':s['thread_id'],'source_line':i})
  if by_line:errors.append({'missing_raw_message_lines':s['thread_id'],'lines':list(by_line)})
  message_count+=len(trs)
 for att in conv['attachments']:
  if att.get('missing'):continue
  if sha(A/att['archive_path'])!=att['sha256']:errors.append({'attachment_hash':att['archive_path']})
 checks['attachment_missing_count']=sum(x.get('missing',False) for x in conv['attachments'])
 snapshots=load(A/'manifests/source_snapshot.json')
 for r in snapshots:
  if sha(A/r['archive_path'])!=r['sha256']:errors.append({'source_snapshot_hash':r['archive_path']})
 if args.check_originals:
  checked=0
  for name,row in rows.items():
   p=source/name
   if row['type']=='file':
    if not p.is_file() or sha(p)!=row['sha256']:errors.append({'original_changed':name})
    checked+=1
   elif row['type']=='symlink':
    if not p.is_symlink() or os.readlink(p)!=row['target']:errors.append({'original_symlink_changed':name})
  checks['original_files_rehashed']=checked
  for g in load(A/'manifests/git_sources.json'):
   repo=Path(g['source_path']);head=run(['git','-C',str(repo),'rev-parse','HEAD']).decode().strip()
   status=run(['git','-C',str(repo),'status','--porcelain=v1','-z','--untracked-files=all'])
   same=head==g['head'] and hashlib.sha256(status).hexdigest()==g['status_sha256'] and sha(repo/'.git/index')==g['index_sha256_before']
   checks[g['name']+'_head_index_status_unchanged']=same
   if not same:errors.append({'source_git_changed':g['name']})
  for r in snapshots:
   if sha(Path(r['source']))!=r['sha256']:errors.append({'snapshot_source_changed':r['source']})
 if args.restore_smoke:
  g=next(x for x in load(A/'manifests/git_sources.json') if x['bundle'])
  dest=A/'private/restore_smoke/git-history'
  if dest.exists():raise RuntimeError('Git restore smoke destination already exists')
  run(['git','clone','--no-checkout',str(A/g['bundle']),str(dest)])
  checks['git_bundle_clone_head_matches']=run(['git','-C',str(dest),'rev-parse','HEAD']).decode().strip()==g['head']
  checks['restore_smoke_sample_count']=len(smoke)
  checks['restore_smoke_all_hashes_match']=all(s['sha256_matches'] for s in smoke) and len(smoke)==len(samples)
 for k,v in checks.items():
  if v is False:errors.append({'failed_check':k})
 result={'schema':'archive-verification-v1','checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'passed' if not errors else 'failed','checks':checks,'tar_regular_files':file_count,'tar_regular_bytes':byte_count,'conversation_records':len(conv['sessions']),'visible_messages':message_count,'source_snapshot_files':len(snapshots),'restore_samples':smoke,'errors':errors,'scope':'byte preservation and readable export integrity; no experiments/models/solvers invoked; no assertion of production runtime reproducibility; same-disk backup only'}
 out=A/args.output;out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(result,ensure_ascii=False),flush=True)
 return 0 if not errors else 1

if __name__=='__main__':raise SystemExit(main())
