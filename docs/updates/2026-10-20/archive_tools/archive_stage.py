#!/usr/bin/env python3
"""Read-only source capture and sanitized three-layer archive. Never runs evidence."""
import argparse, collections, datetime as dt, difflib, hashlib, importlib.util, io, json, os, re, socket, subprocess, tarfile
from pathlib import Path
import sys
import functools
from concurrent.futures import ProcessPoolExecutor
from collections import deque
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[4]
DEST = ROOT / 'docs/updates/2026-10-20'
def sha(b): return hashlib.sha256(b).hexdigest()
def save(p,v):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def loadmod(name,p):
 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
policy=loadmod('policy',ROOT/'docs/updates/2026-10-17/archive_tools/build_public_followup.py')
previous=loadmod('previous',ROOT/'docs/updates/2026-10-19/archive_tools/archive_harness_s0.py')
policy.ROOT=ROOT
# The same policy patterns, guarded by cheap literal searches for large trajectories.
MOBILE=re.compile(r'1[3-9]\d{9}(?![\w.])')
BIRTH_DATE=re.compile(r'(?:19|20)\d{2}\.\d{2}\.\d{2}(?!\d)')
EMAIL=re.compile(r'(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
LOCAL_IDENTITIES=((str(ROOT),'__PROJECT_ROOT__'),(str(Path.home()),'__HOME__'),(policy.HOST,'__HOST__'))
SENTINELS={'opaque_ciphertext':'gAAAA','api_key':'sk-','github_token':'gh','github_fine_token':'github_pat_','bearer':'bearer','jwt':'eyJ','private_key':'PRIVATE KEY'}
def text(s):
 return short_text(s) if len(s)<256 else sanitize_text_full(s)
@functools.lru_cache(maxsize=16384)
def short_text(s):return sanitize_text_full(s)
DECORATOR=re.compile(r'@(?:functools|contextlib|pytest|dataclasses|unittest|typing|abc|mock)(?:\.[A-Za-z_][A-Za-z0-9_]*)+')
def sanitize_text_full(s):
 protected=[]
 def protect(m):
  before=s[max(0,m.start()-64):m.start()].rstrip(' \t')
  after=s[m.end():m.end()+1]
  if after!='(' and before and not before.endswith(('\n','\\n','`','"',"'")):return m[0]
  protected.append(m[0]);return '__CODE_DECORATOR_'+str(len(protected)-1)+'__'
 s=DECORATOR.sub(protect,s) if '@' in s else s
 if 'data:' in s and any(word in s for word in ('reasoning','thinking','image')):
  lines=[]
  for line in s.splitlines(keepends=True):
   if line.startswith('data:'):
    try:line='data: '+json.dumps(clean(json.loads(line[5:].strip())),ensure_ascii=False)+'\n'
    except ValueError:pass
   lines.append(line)
  s=''.join(lines)
 for old,new in LOCAL_IDENTITIES:
  if old in s:s=s.replace(old,new)
 if '/Users/' in s or '/home/' in s:s=re.sub(r'/(?:Users|home)/[^/\s\\"<>]+','__HOME__',s)
 if '%2' in s:s=re.sub(r'(?i)%2f(?:users|home)%2f[^/%\s]+','__HOME__',s)
 for key,pattern,replacement in policy.PATTERNS:
  if key=='github_token' and not any(x in s for x in ('ghp_','gho_','ghu_','ghs_','ghr_')):continue
  haystack=s.lower() if key=='bearer' else s
  if SENTINELS[key] in haystack:s=pattern.sub(replacement,s)
 if '@' in s:
  s=EMAIL.sub('__EMAIL__',s);s=re.sub(r'@[A-Za-z0-9.-]+\.[A-Za-z]{2,}','__EMAIL_DOMAIN__',s)
 if '1' in s:
  s=MOBILE.sub(lambda m:m[0] if m.start() and (s[m.start()-1].isalnum() or s[m.start()-1] in '_.') else '__PERSONAL_REMOVED__',s)
 if '.' in s:s=BIRTH_DATE.sub('__PERSONAL_REMOVED__',s)
 if '/' in s:s=re.sub(r'(?:(?<![\w./-])|(?<=\\n)|(?<=\\r)|(?<=file://)|(?<=sqlite://))/(workspace|tmp|private|opt|Users|home|root|mnt|var/folders)(?=/|\b)',lambda m:'__LOCAL_'+m[1].replace('/','_').upper()+'__',s)
 if '.local' in s or '.internal' in s:s=re.sub(r'(?i)(?:[A-Za-z0-9._-]+\.)?(?:local|internal)\b','__LOCAL_HOST__',s)
 if 'data:image/' in s:s=re.sub(r'data:image/[^;\s]+;base64,[A-Za-z0-9+/=\s]+','[图片附件未公开]',s)
 if 'iVBOR' in s or '/9j/' in s:s=re.sub(r'(?:iVBORw0KGgo|/9j/)[A-Za-z0-9+/=]{20,}','[图片附件未公开]',s)
 if '<thinking>' in s or '<analysis>' in s:s=re.sub(r'(?is)<(?:thinking|analysis)>.*?</(?:thinking|analysis)>','[非公开内容已移除]',s)
 for i,value in enumerate(protected):s=s.replace('__CODE_DECORATOR_'+str(i)+'__',value)
 return s
policy.sanitize_text=text
policy.SECRET_KEYS.update({'cookie','set-cookie','proxy-authorization','signature','thinking','redacted_thinking'})
base_clean=policy.clean
def clean(v,depth=0):
 if isinstance(v,dict):
  if str(v.get('type','')).startswith(('thinking','redacted_thinking','reasoning','agent_reasoning','response.reasoning')) or v.get('channel') in ('analysis','summary'):
   return {'publication_omitted':'non_user_facing_content'}
  if v.get('type') in ('image','image_url','input_image','output_image'):
   return {'type':'text','text':'[图片附件未公开]'}
  result={}
  for k,x in v.items():
   if k.lower() in ('signature','thinking','redacted_thinking'):continue
   result[text(k)]='__PRIVATE_VALUE_REMOVED__' if k.lower() in policy.SECRET_KEYS and x not in (None,'',False) else clean(x,depth+1)
  return result
 return base_clean(v,depth)
policy.clean=clean

def transform(raw):
 try:s=raw.decode('utf-8')
 except UnicodeError:return None,'binary_private_only'
 if '\x00' in s:return None,'binary_private_only'
 if any(x in s for x in ('response.reasoning','reasoning_content','<thinking>','<analysis>')) and not s.lstrip().startswith(('{','[')):
  return None,'unstructured_internal_content_private_only'
 # Structured content needs recursive removal; ordinary scientific text only substitutions.
 blocks=('thinking','response.reasoning','reasoning_text','"reasoning"','reasoning\\"','agent_reasoning','reasoning_summary','channel','"signature"','image','"image_url"','"input_image"','"output_image"',*policy.SECRET_KEYS)
 if any(x in s for x in blocks):return policy.transform(raw)
 return text(s).encode('utf-8'),None

def classify(p):
 if p.is_symlink():return 'symlink_not_followed'
 n=p.name;parts=p.parts
 if n in ('auth.json','credentials.json','.env') or n.startswith('.env.') or p.suffix in ('.pem','.key'):return 'credential_not_read'
 if any(x in parts for x in ('__pycache__','.git','.venv','venv','node_modules','.cache')):return 'rebuildable_cache'
 if n.endswith(('.sqlite','.sqlite-shm','.sqlite-wal','.db','.pyc','.pstats')):return 'runtime_database_or_binary_profile'
 if n in ('installation_id','.sqlite-maintenance.lock') or any(x.startswith('arg0-') for x in parts):return 'cli_runtime_state'
 if p.suffix not in ('.json','.jsonl','.txt','.log','.md','.py','.sh','.diff','.patch','.toml','.stderr','.done','.before','.lock',''):return 'unsupported_binary_or_runtime'
 return None

def capture(args):
 out=args.output;private=out/'private';private.mkdir(mode=0o700,parents=True,exist_ok=True);private.chmod(0o700)
 snap=private/'snapshot';assert not snap.exists(), 'Capture is immutable; use another output directory'
 snap.mkdir()
 task=args.redactions_from_task or out.parent/'TASK_ARCHIVE_20261020.md'
 identifiers=sorted(set(re.findall(r'\b1[3-9]\d{9}\b|\b(?:19|20)\d{2}\.\d{2}\.\d{2}\b|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',task.read_text()))) if task.exists() else []
 save(private/'redactions.json',identifiers)
 start=dt.datetime.now(dt.timezone.utc); entries=[];excluded=[];sessions=[]
 # Inventory sizes first: growing sessions are captured to exactly these lengths.
 todo=[]
 for p in sorted(args.s1.rglob('*')):
  if not p.is_file() and not p.is_symlink():continue
  name='s1/'+p.relative_to(args.s1).as_posix();why=classify(p)
  if why:excluded.append({'path':name,'reason':why});continue
  todo.append((p,name,p.stat().st_size))
 vrel=Path('docs/updates/2026-10-17/project/experiments/harness_v6_20261017')
 for p in sorted((ROOT/vrel).rglob('*')):
  if not p.is_file() and not p.is_symlink():continue
  name='source/v6/'+p.relative_to(ROOT/vrel).as_posix();why=classify(p)
  if why:excluded.append({'path':name,'reason':why});continue
  todo.append((p,name,p.stat().st_size))
 claude=args.claude
 for p in sorted(claude.rglob('*')):
  rel=p.relative_to(claude)
  if not p.is_file() or not (len(rel.parts)==1 and p.suffix=='.jsonl' or 'subagents' in rel.parts and p.suffix=='.jsonl' or 'tool-results' in rel.parts):continue
  name='conversations/claude/'+rel.as_posix();todo.append((p,name,p.stat().st_size))
  if 'tool-results' not in rel.parts:sessions.append({'path':name,'kind':'claude-subagent' if 'subagents' in rel.parts else 'claude-main','id':p.stem,'parent':rel.parts[0] if 'subagents' in rel.parts else None})
 prior_ids=set()
 for p in ROOT.glob('docs/updates/*/conversations/index.json'):
  if '2026-10-20' in str(p):continue
  for row in json.loads(p.read_text()).get('sessions',[]):prior_ids.add(row.get('thread_id',row.get('id')))
 candidates=[]
 for day in ('19','20'):candidates+=list((args.codex/'sessions/2026/10'/day).glob('*.jsonl'))
 candidates+=list((args.codex/'archived_sessions').rglob('*.jsonl'))
 for p in sorted(set(candidates)):
  with p.open() as f:
   try:meta=json.loads(next(f)).get('payload',{})
   except (ValueError,StopIteration):continue
  cwd=meta.get('cwd','');sid=meta.get('id',p.stem)
  if not (str(ROOT) in cwd or str(args.s1.parent) in cwd):continue
  # No Oct-19 conversation export exists. Include not-previously-archived sessions.
  assert sid not in prior_ids, 'Previously archived session needs explicit record cutoff'
  name='conversations/codex/'+p.name;todo.append((p,name,p.stat().st_size))
  sessions.append({'path':name,'kind':'codex','id':sid,'parent':meta.get('source',{}).get('subagent') if isinstance(meta.get('source'),dict) else None,'selection':'not_previously_archived'})
 cutoff=dt.datetime.now(dt.timezone.utc)
 for i,(p,name,size) in enumerate(todo):
  dst=snap/name;dst.parent.mkdir(parents=True,exist_ok=True)
  h=hashlib.sha256();left=size
  with p.open('rb') as src,dst.open('wb') as target:
   while left:
    b=src.read(min(left,4*1024*1024));assert b,(name,'source shrank');target.write(b);h.update(b);left-=len(b)
  entries.append({'path':name,'bytes':size,'sha256':h.hexdigest(),'source_changed_after_inventory':p.stat().st_size!=size})
  if i%500==0:print('captured',i,len(todo),flush=True)
 # Preserve existing user-authored deliverables with recorded hashes.
 protected=[DEST/'COMPARISON_DRAFT.md',*sorted((ROOT/'docs/career-application/2026-10-20-semiconductor-agent-portfolio').rglob('*'))]
 protected=[{'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p.read_bytes())} for p in protected if p.is_file()]
 record={'inventory_started_utc':start.isoformat(),'cutoff_utc':cutoff.isoformat(),'cutoff_beijing':cutoff.astimezone(dt.timezone(dt.timedelta(hours=8))).isoformat(),'capture_finished_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'semantics':'Per-file size-bounded prefix captured after inventory; not an atomic filesystem snapshot. Current Claude and Codex sessions are prefixes.','previous_conversation_cutoff_utc':'2026-10-17T06:02:18+00:00','oct19_explicit_conversation_cutoff':None,'selection_reason':'Oct-19 archive has no conversations or explicit capture cutoff; all selected Codex IDs are absent from prior conversation indexes. Includes one earlier Oct-19 unarchived session.','files':entries,'sessions':sessions,'excluded':excluded,'protected':protected}
 save(private/'capture.json',record);print('capture complete',len(entries),flush=True)

def add(t,name,b):
 info=tarfile.TarInfo(name);info.size=len(b);info.mode=0o644;info.mtime=0;t.addfile(info,io.BytesIO(b))
def export_session(raw,s,cutoff):
 messages=[];tools=[];times=[];invalid=0;counts=collections.Counter()
 for line_no,line in enumerate(raw.splitlines(),1):
  try:r=json.loads(line)
  except ValueError:invalid+=1;continue
  stamp=r.get('timestamp');
  if stamp:times.append(stamp)
  if s['kind'].startswith('claude'):
   msg=r.get('message',{});role=msg.get('role');content=msg.get('content',[])
   if role not in ('user','assistant'):continue
   if isinstance(content,str):content=[{'type':'text','text':content}]
   texts=[]
   for block in content:
    typ=block.get('type') if isinstance(block,dict) else None
    if typ=='text':texts.append(text(block['text']))
    elif typ=='image':texts.append('[图片附件未公开]')
    elif typ in ('tool_use','tool_result'):
     tools.append({'timestamp':stamp,'source_line':line_no,'type':typ,'name':block.get('name'),'id':block.get('id',block.get('tool_use_id')),'source_record_sha256':sha(line)})
    elif typ in ('thinking','redacted_thinking'):counts['private_blocks_omitted']+=1
   if texts:messages.append({'role':role,'timestamp':stamp,'source_line':line_no,'text':'\n\n'.join(texts)})
  else:
   p=r.get('payload',{});typ=p.get('type')
   if r.get('type')=='response_item':
    if typ=='message' and p.get('role') in ('user','assistant') and p.get('channel') not in ('analysis','summary'):
     texts=[]
     for b in p.get('content',[]):
      if b.get('type') in ('input_text','output_text','text'):texts.append(text(b.get('text','')))
      elif 'image' in b.get('type',''):texts.append('[图片附件未公开]')
     if texts:messages.append({'role':p['role'],'timestamp':stamp,'source_line':line_no,'text':'\n\n'.join(texts)})
    elif typ in ('function_call','function_call_output','custom_tool_call','custom_tool_call_output'):
     tools.append({'timestamp':stamp,'source_line':line_no,'type':typ,'name':p.get('name'),'call_id':p.get('call_id'),'source_record_sha256':sha(line)})
    elif typ=='reasoning' or p.get('channel') in ('analysis','summary'):counts['private_blocks_omitted']+=1
 title=next((m['text'].strip().split('\n')[0].lstrip('# ')[:100] for m in messages if m['role']=='user' and not m['text'].strip().startswith(('<','# AGENTS.md'))),'会话 '+s['id'])
 out=DEST/'conversations';out.mkdir(exist_ok=True)
 stem=s['kind']+'-'+s['id']
 for suffix,records in (('.jsonl',messages),('.tools.jsonl',tools)):(out/(stem+suffix)).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in records))
 lines=[f'# {title}','','此为截止点的前缀快照；私人内容及图片未公开。工具索引另见 tools.jsonl；工具正文留在私有包，仅公开位置与哈希。','']
 for m in messages:lines += [f'## {m["role"]} · {m["timestamp"]} · 原记录 L{m["source_line"]}','',m['text'],'']
 (out/(stem+'.md')).write_text('\n'.join(lines))
 return {**s,'session_role':'subagent' if s['parent'] else 'main','title':title,'raw_prefix_sha256':sha(raw),'time_start':min(times) if times else None,'time_end':max(times) if times else None,'visible_messages':len(messages),'message_counts_by_role':dict(collections.Counter(m['role'] for m in messages)),'raw_records':len(raw.splitlines()),'tool_records':len(tools),'incomplete_records':invalid,**counts,'transcript_md':stem+'.md','transcript_jsonl':stem+'.jsonl','tool_index':stem+'.tools.jsonl'}

def transform_entry(job):
 source,cached,expected=job
 if cached:
  b=Path(cached).read_bytes();assert sha(b)==expected;return b,None
 if '/conversations/' in source:return None,'conversation_private_only'
 return transform(Path(source).read_bytes())
def prepared_entries(entries,snap,out):
 cache_path=out/'private/cache-index.json'
 cache=json.loads(cache_path.read_text()) if cache_path.exists() else {}
 def job(e):
  row=cache.get(e['path']);cached=None;expected=None
  if row and row['source_sha256']==e['sha256']:
   cached=str(out/'private/public-cache'/e['path']);expected=row['sha256']
  return str(snap/e['path']),cached,expected
 iterator=iter(entries)
 with ProcessPoolExecutor(max_workers=2) as pool:
  pending=deque()
  for _ in range(3):
   e=next(iterator,None)
   if e:pending.append((e,pool.submit(transform_entry,job(e))))
  while pending:
   e,future=pending.popleft();public,reason=future.result()
   following=next(iterator,None)
   if following:pending.append((following,pool.submit(transform_entry,job(following))))
   yield e,public,reason

def build(args):
 out=args.output;capture=json.loads((out/'private/capture.json').read_text());snap=out/'private/snapshot'
 release=out/'release';release.mkdir(exist_ok=True);records=[];original=[];excluded=list(capture['excluded']);rows=[]
 sessions={s['path']:s for s in capture['sessions']}
 public=release/'harness-v6-s1-public.tar.gz';private=out/'private/harness-v6-s1-original-selected.tar.gz'
 with tarfile.open(private,'w:gz',compresslevel=1) as pt,tarfile.open(public,'w:gz',compresslevel=1) as pub:
  for i,(e,sanitized,why) in enumerate(prepared_entries(capture['files'],snap,out)):
   name=e['path'];raw=(snap/name).read_bytes();assert sha(raw)==e['sha256'];add(pt,name,raw);original.append(e)
   if name.startswith('conversations/'):
    if name in sessions:rows.append(export_session(raw,sessions[name],capture['cutoff_utc']))
    else:excluded.append({'path':name,'reason':'tool_spill_private_only_public_reference_in_index','source_sha256':sha(raw),'bytes':len(raw)})
    continue
   if why:excluded.append({'path':name,'reason':why,'source_sha256':sha(raw),'bytes':len(raw)});continue
   add(pub,name,sanitized);records.append({'path':name,'source_sha256':sha(raw),'sha256':sha(sanitized),'bytes':len(sanitized),'transformed':raw!=sanitized})
   # Small stage records and all stage scripts are readable in Git; large trajectories remain in release.
   parts=Path(name).parts
   selected=(len(parts)==3 and parts[1] in ('goal','stage-s1','audit-opt') and Path(name).suffix in ('.md','.json')) or (name.startswith('s1/stage-s1/w5/') and len(parts)==4 and Path(name).suffix=='.json') or (name.startswith('s1/TASK_PHASE_'))
   if selected and len(sanitized)<500000:
    dst=DEST/'evidence/records'/name;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(sanitized)
   if i%250==0:print('packaged',i,len(capture['files']),flush=True)
  add(pt,'manifest.json',json.dumps({'files':original}).encode())
  manifest={'schema':'harness-v6-s1-selected-v1','cutoff_utc':capture['cutoff_utc'],'files':records,'original_signatures':'Historical raw hashes; transformed bytes must use public hashes.','model_calls':0}
  add(pub,'manifest.json',json.dumps(manifest,ensure_ascii=False).encode())
  ex=''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in excluded).encode();add(pub,'excluded.jsonl',ex)
 save(release/'manifest.json',manifest);(DEST/'evidence/excluded.jsonl').write_bytes(ex)
 save(out/'private/manifest.json',{'files':original,'archive_sha256':sha(private.read_bytes())})
 index={k:capture[k] for k in ('cutoff_utc','cutoff_beijing','previous_conversation_cutoff_utc','oct19_explicit_conversation_cutoff','selection_reason','semantics')};index.update({'sessions':rows,'counts':dict(collections.Counter(s['kind'] for s in rows)),'visible_messages':sum(s['visible_messages'] for s in rows),'tool_spills':[e for e in excluded if 'tool_spill' in e['reason']]})
 save(DEST/'conversations/index.json',index)
 lines=['# 会话索引','',f'截止 UTC {capture["cutoff_utc"]} / 北京时间 {capture["cutoff_beijing"]}。当前会话是前缀快照。','', '10 月 19 日归档没有会话导出或明确会话截止；本次按“未归档会话”选择，所选 Codex ID 均未出现在旧索引。实验专用 home 的 rollout 归入科学证据。原始字节与工具 spill 仅保存在私有包，公开 tools.jsonl 提供调用位置；内部推理和图片不公开。','','| 会话 | 类型 / 父会话 | 消息 |','|---|---|---:|']
 for s in rows:lines.append(f'| [{s["title"].replace("|","／")}]({s["transcript_md"]}) | {s["kind"]} / {s["parent"] or "—"} | {s["visible_messages"]} |')
 (DEST/'conversations/README.md').write_text('\n'.join(lines)+'\n')
 save(DEST/'verification/capture.json',{k:v for k,v in capture.items() if k not in ('files','sessions','excluded')})
 result={'files':len(records),'logical_bytes':sum(e['bytes'] for e in records),'archive_bytes':public.stat().st_size,'archive_sha256':sha(public.read_bytes()),'private_files':len(original),'private_bytes':private.stat().st_size,'private_sha256':sha(private.read_bytes()),'sessions':index['counts'],'messages':index['visible_messages'],'excluded':dict(collections.Counter(e['reason'] for e in excluded)),'model_calls':0}
 save(DEST/'verification/archive-build.json',result);save(release/'archive-build.json',result)
 print(json.dumps(result),flush=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('command',choices=['capture','build']);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--s1',type=Path);parser.add_argument('--claude',type=Path);parser.add_argument('--codex',type=Path);parser.add_argument('--redactions-from-task',type=Path)
 args=parser.parse_args();globals()[args.command](args)
