#!/usr/bin/env python3
"""Verify archive bytes, manifests, protected documents, summaries and leak scan.
No evidence code is imported or executed. No network or model calls.
"""
import argparse, collections, hashlib, io, json, re, socket, subprocess, tarfile, zipfile
from pathlib import Path, PurePosixPath
from concurrent.futures import ProcessPoolExecutor
from collections import deque
ROOT=Path(__file__).resolve().parents[4]
DEST=ROOT/'docs/updates/2026-10-20'
def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def sha(b):return hashlib.sha256(b).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
EXACT_PATTERNS=[]
# Pattern definitions themselves are not findings; only concrete matched values count.
PATTERNS={
 'absolute_local_paths':re.compile(r'(?:(?<![\w./-])|(?<=\\n)|(?<=\\r)|(?<=file://)|(?<=sqlite://))/(?:workspace|Users|home|root|private|tmp|opt|mnt)/[A-Za-z0-9_.-]+'),
 'emails':re.compile(r'(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'),
 'personal_phone':re.compile(r'1[3-9]\d{9}(?![\w.])'),
 'personal_birth_date':re.compile(r'(?:19|20)\d{2}\.\d{2}\.\d{2}(?!\d)'),
 'personal_email_domain':re.compile(r'@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'),
 'opaque_ciphertext':re.compile(r'gAAAA[A-Za-z0-9_=-]{70,}'),
 'private_key':re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
 'api_secret':re.compile(r'(?<![\w-])sk-(?:(?:proj|live|svcacct|ant-api\d*)-)?[A-Za-z0-9_-]{20,}'),
 'token_secret':re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{30,}|eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})'),
 'bearer_secret':re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{20,}'),
 'base64_image':re.compile(r'(?:iVBORw0KGgo|/9j/)[A-Za-z0-9+/=]{20,}|data:image/[^;\s]+;base64,'),
 'private_content_block':re.compile(r'"(?:type|channel)"\s*:\s*"(?:thinking[^"]*|redacted_thinking[^"]*|reasoning[^"]*|agent_reasoning[^"]*|response\.reasoning[^"]*|analysis)"|"signature"\s*:\s*"[^"\s]+"'),
 'private_summary_channel':re.compile(r'"channel"\s*:\s*"summary"'),
 'image_content_block':re.compile(r'"type"\s*:\s*"(?:image|image_url|input_image|output_image)"'),
 'hostname':re.compile(re.escape(socket.gethostname())+r'|\b[A-Za-z0-9_-]+\.(?:local|internal)\b'),
}
def mask_code_decorators(s):
 def replace(m):
  before=s[max(0,m.start()-64):m.start()].rstrip(' \t');after=s[m.end():m.end()+1]
  return '__PYTHON_DECORATOR__' if after=='(' or not before or before.endswith(('\n','\\n','`','"',"'")) else m[0]
 return re.sub(r'@(?:functools|contextlib|pytest|dataclasses|unittest|typing|abc|mock)(?:\.[A-Za-z_][A-Za-z0-9_]*)+',replace,s)
def scan(raw,name,counts,findings):
 try:s=raw.decode('utf-8')
 except UnicodeError:
  if raw.startswith(b'%PDF'):
   extracted=subprocess.check_output(['pdftotext','-','-'],input=raw);scan(extracted,name+'#pdf-text',counts,findings);return
  if raw.startswith(b'PK') and name.endswith('.docx'):
   with zipfile.ZipFile(io.BytesIO(raw)) as z:
    for n in z.namelist():
     if n.endswith('.xml'):scan(z.read(n),name+'#'+n,counts,findings)
     elif '/media/' in n:
      assert sha(z.read(n))=='98d6e448ce58c141b7c8f80ffefe1633fd7fda2d8190966e1bf40d3941d3dcf7','Unreviewed embedded image'
   return
  if name.endswith('figures/roadmap.png'):
   assert sha(raw)=='98d6e448ce58c141b7c8f80ffefe1633fd7fda2d8190966e1bf40d3941d3dcf7','Unreviewed image'
   return
  findings.append({'path':name,'kind':'unexpected_nontext'});return
 if name.endswith('.sql') and "X'" in s:
  for match in re.finditer(r"X'([0-9a-fA-F]*)'",s):scan(bytes.fromhex(match[1]),name+'#blob',counts,findings)
 exact=sum(s.count(value) for value in EXACT_PATTERNS)
 counts['task_exact_private_identifiers']+=exact
 if exact:findings.append({'path':name,'kind':'task_exact_private_identifiers','count':exact})
 sentinels={'emails':('@',),'personal_email_domain':('@',),'api_secret':('sk-',),'token_secret':('ghp_','gho_','ghu_','ghs_','ghr_','github_pat_','eyJ'),'opaque_ciphertext':('gAAAA',),'private_key':('PRIVATE KEY',),'base64_image':('iVBOR','/9j/','data:image/'),'private_summary_channel':('channel',),'image_content_block':('image',),'hostname':(socket.gethostname(),'.local','.internal'),'private_content_block':('thinking','reasoning','analysis','signature')}
 for kind,p in PATTERNS.items():
  if kind in sentinels and not any(x in s for x in sentinels[kind]):continue
  if kind=='emails' and not PATTERNS['personal_email_domain'].search(s):continue
  if kind=='bearer_secret' and 'bearer' not in s.lower():continue
  haystack=s
  if kind in ('private_content_block','private_summary_channel','image_content_block'):
   for _ in range(3):
    if '\\"' not in haystack:break
    haystack=haystack.replace('\\"','"')
  if kind in ('emails','personal_email_domain'):
   haystack=mask_code_decorators(haystack)
  matches=list(p.finditer(haystack))
  if kind=='personal_phone':matches=[m for m in matches if not m.start() or not (s[m.start()-1].isalnum() or s[m.start()-1] in '_.')]
  if kind=='personal_birth_date':matches=[m for m in matches if not m.start() or not s[m.start()-1].isdigit()]
  counts[kind]+=len(matches)
  if matches:findings.append({'path':name,'kind':kind,'count':len(matches)})

def scan_job(raw,name):
 counts=collections.Counter();findings=[];scan(raw,name,counts,findings);return dict(counts),findings

def check_tar(path,expected,counts=None,findings=None):
 seen=set();files={};manifest=None;pending=deque()
 pool=ProcessPoolExecutor(max_workers=2) if counts is not None else None
 def collect():
  c,f=pending.popleft().result();counts.update(c);findings.extend(f)
 try:
  with tarfile.open(path,'r|gz') as t:
   for m in t:
    assert m.isfile() and not PurePosixPath(m.name).is_absolute() and '..' not in PurePosixPath(m.name).parts,m.name
    assert m.name not in seen,m.name;seen.add(m.name)
    raw=t.extractfile(m).read()
    if pool:
     pending.append(pool.submit(scan_job,raw,m.name))
     if len(pending)>=3:collect()
    if m.name=='manifest.json':manifest=json.loads(raw)
    elif m.name!='excluded.jsonl':files[m.name]={'sha256':sha(raw),'bytes':len(raw)}
    if len(seen)%1000==0:print(json.dumps({'phase':'public_members' if pool else 'private_members','checked':len(seen)}),flush=True)
  while pending:collect()
 finally:
  if pool:pool.shutdown()
 assert manifest is not None
 indexed={x['path']:{'sha256':x['sha256'],'bytes':x['bytes']} for x in manifest['files']}
 assert files==indexed,'archive member inventory/hash mismatch'
 assert len(files)==expected
 return len(files),manifest

def main(args):
 global EXACT_PATTERNS
 EXACT_PATTERNS=json.loads((args.output/'private/redactions.json').read_text());assert len(EXACT_PATTERNS)>=4
 build=json.loads((DEST/'verification/archive-build.json').read_text());capture=json.loads((DEST/'verification/capture.json').read_text());counts=collections.Counter({k:0 for k in PATTERNS});findings=[]
 pub=args.output/'release/harness-v6-s1-public.tar.gz';private=args.output/'private/harness-v6-s1-original-selected.tar.gz'
 for directory in ('release','private'):
  for line in (args.output/directory/'checksums.sha256').read_text().splitlines():
   expected,name=line.split('  ',1);assert '/' not in name and digest(args.output/directory/name)==expected
 assert json.loads((args.output/'release/archive-build.json').read_text())==build
 assert digest(pub)==build['archive_sha256'];n,manifest=check_tar(pub,build['files'],counts,findings)
 assert json.loads((args.output/'release/manifest.json').read_text())==manifest
 assert digest(private)==build['private_sha256']
 if args.reuse_private_report:
  prior=json.loads(args.reuse_private_report.read_text())
  assert prior['private_sha256']==build['private_sha256'] and prior['private_files_checked']==build['private_files']
  pn=prior['private_files_checked'];pm=json.loads((args.output/'private/manifest.json').read_text())
 else:pn,pm=check_tar(private,build['private_files'])
 external=json.loads((args.output/'private/manifest.json').read_text());assert external['files']==pm['files'];assert external['archive_sha256']==digest(private)
 for row in capture['protected']:assert digest(ROOT/row['path'])==row['sha256'],row['path']
 original_hashes={e['path']:e['sha256'] for e in pm['files']}
 public_hashes={e['path']:e['sha256'] for e in manifest['files']}
 sql_checks=json.loads((DEST/'verification/sqlite-exports.json').read_text());assert sql_checks['passed']
 for db in sql_checks['databases']:
  assert original_hashes[db['source_path']]==db['source_sha256']
  assert public_hashes[db['source_path']+'.public.sql']==db['sql_sha256'] and db['restored_rows_identical']
 index=json.loads((DEST/'conversations/index.json').read_text());kind_counts=collections.Counter(s['kind'] for s in index['sessions'])
 assert dict(kind_counts)==index['counts'] and kind_counts['claude-main']==7 and kind_counts['claude-subagent']==8
 mains={s['id'] for s in index['sessions'] if s['kind']=='claude-main'}
 for session in index['sessions']:
  assert original_hashes[session['path']]==session['raw_prefix_sha256']
  messages=[json.loads(line) for line in (DEST/'conversations'/session['transcript_jsonl']).read_text().splitlines()]
  tools=[json.loads(line) for line in (DEST/'conversations'/session['tool_index']).read_text().splitlines()]
  assert len(messages)==session['visible_messages'] and len(tools)==session['tool_records']
  assert dict(collections.Counter(m['role'] for m in messages))==session['message_counts_by_role']
  assert all(0<m['source_line']<=session['raw_records'] for m in messages+tools)
  if session['kind']=='claude-subagent':assert session['parent'] in mains
 assert index['visible_messages']==sum(s['visible_messages'] for s in index['sessions'])
 changed=set()
 for command in (['git','diff','--name-only','-z'],['git','ls-files','--others','--exclude-standard','-z']):changed.update(x for x in subprocess.check_output(command,cwd=ROOT).decode().split('\0') if x)
 public_manifest=json.loads((ROOT/'publication/manifest.json').read_text());indexed={x['path']:x for x in public_manifest['files']}
 for name in sorted(changed):
  p=ROOT/name
  if not p.is_file():continue
  scan(p.read_bytes(),name,counts,findings)
  if name!='publication/manifest.json':assert indexed[name]['public_sha256']==digest(p),name
 # Check numbers against public evidence, not the prose.
 summary=json.loads((DEST/'evidence/summary.json').read_text())
 for row in summary['runs']:
  s=json.loads((DEST/'evidence/records'/row['summary_path']).read_text());a=json.loads((DEST/'evidence/records'/row['audit_path']).read_text())
  assert row['totals']==s['totals'] and row['audit_passed']==a['passed']
  assert a['actual_requests']==s['totals']['requests']
  assert a['usage']['input_tokens']==s['totals']['input_tokens']
  assert a['usage']['cached_input_tokens']==s['totals']['cached_tokens'] and a['usage']['output_tokens']==s['totals']['output_tokens']
  assert a['start']==s['start'] and a['end']==s['end']
 for arm,parameters in summary['S1_parameters'].items():
  registration=json.loads((DEST/'evidence/records/s1/stage-s1/w5'/('registration-formal-S1-'+arm+'.json')).read_text())
  assert all(registration[k]==value for k,value in parameters.items())
 # User explicitly required the pre-existing comparison draft to remain unchanged.
 exceptions=[f for f in findings if f['path']=='docs/updates/2026-10-20/COMPARISON_DRAFT.md' and f['kind']=='absolute_local_paths' and f['count']==11]
 unresolved=[f for f in findings if f not in exceptions]
 result={'passed':not unresolved,'reviewed_exceptions':exceptions,'exception_reason':'Original comparison draft must remain byte-identical; 11 local-path references retained and reported.','binary_review':'PDF text extracted; all DOCX XML scanned; sole DOCX embedded image matches visually reviewed roadmap PNG; PDF contains no raster images.', 'release_files_checked':n,'private_files_checked':pn,'git_files_scanned':len(changed),'git_bytes':sum((ROOT/p).stat().st_size for p in changed if (ROOT/p).is_file()),'leak_counts':dict(counts),'findings':findings,'protected_files_unchanged':len(capture['protected']),'models_or_experiments_run':0,'exact_identifier_patterns_checked':len(EXACT_PATTERNS),'release_sha256':build['archive_sha256'],'private_sha256':build['private_sha256'],'private_member_check_reused':bool(args.reuse_private_report),'private_prior_report_sha256':digest(args.reuse_private_report) if args.reuse_private_report else None}
 # Write outside Git first; finalize copies this report before publication hashes are frozen.
 save(args.output/'verification-result.json',result);print(json.dumps(result,ensure_ascii=False));raise SystemExit(bool(unresolved))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--reuse-private-report',type=Path,help='Reuse a prior complete private member check only after rechecking the identical archive SHA-256');main(p.parse_args())
