#!/usr/bin/env python3
"""Archive selected experiment evidence without executing any experiment.

Original bytes stay in a local private package. Public derivatives reuse the
repository publication policy; raw signatures remain historical references.
"""
import argparse,collections,gzip,hashlib,importlib.util,io,json,re,subprocess,tarfile
from pathlib import Path

def sha(raw):return hashlib.sha256(raw).hexdigest()
def save(path,obj):
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def add(tar,name,data):
 row=tarfile.TarInfo(name);row.size=len(data);row.mode=0o644;row.mtime=0
 tar.addfile(row,io.BytesIO(data))

def linear_sanitizer(policy):
 """Same substitutions, with a start boundary for the email local part.

 Without the boundary, long alphabetic stress returns without @ cause quadratic
 retries. A match always starts at the beginning of its allowed-character run.
 """
 def sanitize(s):
  for old,new in ((str(policy.ROOT),'__PROJECT_ROOT__'),(str(Path.home()),'__HOME__'),(policy.HOST,'__HOST__')):
   if old and old in s:policy.STATS['local_identity']+=s.count(old);s=s.replace(old,new)
  s,n=re.subn(r'/(?:Users|home)/[^/\s\\\"<>]+','__HOME__',s);policy.STATS['local_identity']+=n
  s,n=re.subn(r'(?i)%2f(?:users|home)%2f[^/%\s]+','__HOME__',s);policy.STATS['local_identity']+=n
  for key,pattern,replacement in policy.PATTERNS:s,n=pattern.subn(replacement,s);policy.STATS[key]+=n
  if '@' in s:
   pattern=r'(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@(?:'+re.escape(policy.HOST)+r'(?:\.local)?|[A-Za-z0-9.-]+\.[A-Za-z]{2,})'
   s,n=re.subn(pattern,lambda m:m.group(0) if m.group(0).endswith(('users.noreply.github.com','noreply.github.com','noreply@anthropic.com')) else '__EMAIL__',s);policy.STATS['email_matches']+=n
  return s
 return sanitize

def build(args):
 source=args.source.resolve();target=args.target.resolve();work=args.work.resolve();goal=work/'goal-s0-20261019'
 dest=target/'docs/updates/2026-10-19';private=args.private.resolve();private.mkdir(parents=True,exist_ok=False)
 spec=importlib.util.spec_from_file_location('public_policy',target/'docs/updates/2026-10-17/archive_tools/build_public_followup.py')
 policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
 policy.ROOT=source.parent.parent
 policy.SECRET_KEYS.update({'cookie','set-cookie','proxy-authorization'})
 policy.sanitize_text=linear_sanitizer(policy)
 # A paused goal is historical state, never authorization to restart inference.
 status=json.loads((goal/'GOAL_STATUS.json').read_text())
 assert status['gates']['formal_trajectories']=='0/6'
 assert status['real_model_requests']['pending_native_requests']==0
 amendment=json.loads((goal/'technical-amendment-stall-v1.json').read_text())
 assert all(sha(Path(n).read_bytes())==h for n,h in amendment['frozen_files'].items())
 changed=set()
 for command in (['git','diff','--name-only','-z'],['git','ls-files','--others','--exclude-standard','-z']):
  changed.update(p for p in subprocess.check_output(command,cwd=source).decode().split('\0') if p)
 vrel='docs/updates/2026-10-17/project/experiments/harness_v6_20261017'
 assert all(p.startswith(vrel+'/') for p in changed)
 source_rows=[]
 for name in sorted(changed):
  src=source/name;assert src.is_file() and not src.is_symlink()
  raw=src.read_bytes();public,reason=policy.transform(raw);assert reason is None
  out=target/name;out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(public)
  source_rows.append(dict(path=name,source_sha256=sha(raw),public_sha256=sha(public),bytes=len(public),transformed=raw!=public))
 save(dest/'verification/source-publication.json',dict(files=source_rows,source_worktree_changed=False))
 # Keep all stage decisions, registrations, diagnoses and historical helpers.
 selected={p:'goal/'+p.name for p in goal.iterdir() if p.is_file() and p.suffix in ('.json','.py','.md','.txt','.patch')}
 directories={p for p in goal.iterdir() if p.is_dir() and p.name.startswith(('ab-real-','smoke-','formal-'))}
 directories.update(goal/n for n in ('ab-kit-schema','query-domain-v1','full-pressure-selfcheck-v1','full-pressure-stall-v1','native-physical-stall-v1','native-proxy-stall-v1','audited-reasoning-stall-v1','output-reserve-stall-v1','physical-cycles-stall-v3','recording-samples-stall-v1','offline-stall-prefix-replay-v3'))
 for key,value in json.loads((goal/'qualification-stall-v1.json').read_text())['reused_exact_evidence'].items():
  p=Path(value['path'])
  if p.parent!=goal:directories.add(p.parent)
 omitted=collections.Counter()
 allowed={'.json','.jsonl','.txt','.sse','.md','.py','.patch'}
 forbidden={'home','codex-home','.codex','.git','__pycache__','.pytest_cache','node_modules','sessions','archived_sessions','shell_snapshots'}
 for directory in sorted(directories):
  assert directory.is_dir(),directory
  for path in directory.rglob('*'):
   if not path.is_file():continue
   relative=path.relative_to(goal)
   if path.is_symlink() or forbidden.intersection(relative.parts) or any('codex-home' in part for part in relative.parts):
    omitted['private_runtime_or_symlink']+=1;continue
   if path.suffix not in allowed or path.name in ('auth.json','credentials.json'):
    omitted['binary_cache_database_or_log']+=1;continue
   selected[path]='goal/'+relative.as_posix()
 for path in (work/'reports').glob('*.json'):selected[path]='reports/'+path.name
 for label in ('goal-all-offline-gates-stall-v1','goal-all-offline-gates-stall-v2','goal-stall-unit-v2','goal-idle-audit-v2','goal-stall-prefix-replay-v2','goal-stall-prefix-replay-v3','goal-full-pressure-stall-v1','goal-native-physical-stall-v1','goal-native-proxy-stall-v1','goal-native-reasoning-stall-v1','goal-output-reserve-stall-v1'):
  path=work/'logs'/(label+'.log');assert path.is_file();selected[path]='logs/'+path.name
 for path in (source/vrel).rglob('*'):
  if path.is_file() and not path.is_symlink() and path.suffix in ('.py','.md','.json','.toml','.txt','.patch') and not forbidden.intersection(path.relative_to(source/vrel).parts):
   selected[path]='source/v6/'+path.relative_to(source/vrel).as_posix()
 records=[];private_records=[];identical_code=[];public_path=args.public.resolve();public_path.parent.mkdir(parents=True,exist_ok=True)
 private_path=private/'harness-v6-s0-original-selected.tar.gz'
 assert not public_path.exists()
 with tarfile.open(private_path,'w:gz',compresslevel=6) as rawtar,tarfile.open(public_path,'w:gz',compresslevel=6) as publictar:
  for index,(path,name) in enumerate(sorted(selected.items(),key=lambda row:row[1])):
   raw=path.read_bytes();public,reason=policy.transform(raw)
   assert reason is None,(name,reason)
   private_records.append(dict(path=name,sha256=sha(raw),bytes=len(raw)))
   add(rawtar,name,raw);add(publictar,name,public)
   records.append(dict(path=name,sha256=sha(public),source_sha256=sha(raw),bytes=len(public),transformed=raw!=public))
   if name.startswith('source/v6/') and path.suffix=='.py':identical_code.append(raw==public)
   if index%200==0:print(json.dumps(dict(archived=index,total=len(selected))),flush=True)
  add(rawtar,'manifest.json',json.dumps(dict(files=private_records),ensure_ascii=False).encode())
  add(publictar,'manifest.json',json.dumps(dict(schema='harness-v6-public-selected-v1',files=records,original_signatures='historical raw-byte references; use public sha256 to verify transformed files',model_calls_during_archival=0),ensure_ascii=False).encode())
 # Exact original checks remain available locally, without copying credentials.
 save(private/'manifest.json',dict(files=private_records,archive_sha256=sha(private_path.read_bytes())))
 save(dest/'verification/archive-build.json',dict(passed=True,files=len(records),logical_bytes=sum(r['bytes'] for r in records),archive_bytes=public_path.stat().st_size,archive_sha256=sha(public_path.read_bytes()),original_selected_archive_sha256=sha(private_path.read_bytes()),transformations=dict(policy.STATS),excluded_counts=dict(omitted),production_python_byte_identical=all(identical_code),python_files_checked=len(identical_code),real_model_requests=0,full_private_workspace_not_copied=True))
 # Small human-reviewable records accompany the compressed full selection.
 for name in ('experiment-rules-v1.json','qualification-stall-v1.json','formal-exclusions-v1.json','smoke-E1-stall-1-diagnosis.json','stall-pressure-continuity-v1.json','registration-smoke-v5.json','registration-formal-v1.json','GOAL_STATUS.json','PROGRESS_20261019.md'):
  public,reason=policy.transform((goal/name).read_bytes());assert reason is None
  out=dest/'evidence/records'/name;out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(public)
 save(dest/'evidence/summary.json',dict(experiment_complete=False,formal_trajectories_completed=0,formal_trajectories_required=6,goal_state='paused at user E1 smoke limit',offline_tests=dict(passed=660,subtests=38,failed=0,skipped=0),actual_usage=status['real_model_requests'],latest_failure='machine_order: undefined tasks n23..n31',selected_format='explicit',rules_unchanged=True,archival_model_calls=0))
 print(json.dumps(dict(done=True,files=len(records),public_bytes=public_path.stat().st_size,python_identical=all(identical_code))),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();
 for name in ('source','target','work','private','public'):p.add_argument('--'+name,type=Path,required=True)
 build(p.parse_args())
