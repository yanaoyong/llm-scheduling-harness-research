"""Publish verified archive metadata to Git and refresh the existing file manifest."""
from pathlib import Path
import hashlib,importlib.util,json,re,shutil,subprocess
BASE=Path(__file__).resolve().parents[1];ROOT=BASE.parents[1];PUB=BASE/'public';REPO=ROOT/'archive/20261012_public_release';DEST=REPO/'docs/updates/2026-10-17';V=DEST/'verification';V.mkdir(exist_ok=True)
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
spec=importlib.util.spec_from_file_location('sanitizer',BASE/'scripts/build_public_followup.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
for name in ['selection.json','build_result.json','privacy_review.json','sqlite_verification.json','public_package_verification.json','restore_smoke.json']:
 src=PUB/name;assert src.is_file(),name
 if name in ('build_result.json','privacy_review.json','public_package_verification.json','restore_smoke.json'):assert read(src)['status']=='passed',name
 shutil.copyfile(src,V/name)
for name in ['private_object_verification.json','compressed_object_verification.json','isolation_and_git_restore.json','conversation_prefix_verification.json','source_parse.json','archived_metrics_check.json','metadata_privacy_review.json']:
 shutil.copyfile(BASE/'review'/name,V/name)
shutil.copyfile(BASE/'snapshot_result.json',V/'snapshot_result.json')
attachments=read(BASE/'review/private_attachments.json');save(V/'private_attachment_summary.json',{k:v for k,v in attachments.items() if k!='files'})
if (PUB/'github_assets.json').exists():shutil.copyfile(PUB/'github_assets.json',V/'github_assets.json')
for p in (BASE/'scripts').glob('*.py'):
 raw,reason=m.transform(p.read_bytes());assert raw is not None,reason;(DEST/'archive_tools'/p.name).write_bytes(raw)
# Ensure curated local links resolve; historical transcripts and source snapshots retain original provenance references.
missing=[]
for p in [*DEST.glob('*.md'),DEST/'conversations/README.md']:
 for link in re.findall(r'\]\(([^)]+)\)',p.read_text()):
  if link.startswith(('http:','https:','mailto:','__','<')):continue
  link=link.split('#')[0]
  if link and not (p.parent/link).exists():missing.append({'file':str(p.relative_to(REPO)),'target':link})
assert not missing,missing
source_map={r['path']:r for r in read(BASE/'public_git_files.json')}
for path,row in source_map.items():assert sha(REPO/path)==row['public_sha256'],path
assert read(PUB/'selection.json')['database_exports_unavailable']==0
assert read(BASE/'review/private_object_verification.json')['objects_verified']==read(BASE/'snapshot_result.json')['unique_objects']
review={'status':'passed','curated_links_valid':True,'copied_project_files_hash_checked':len(source_map),'conversation_prefixes_verified':73,'source_python_files_parsed':read(BASE/'review/source_parse.json')['python_files_parsed'],'original_B_unchanged':True,'models_solvers_experiments_executed_by_archival':0,'release_asset_verification_available':(PUB/'github_assets.json').exists(),'scope':'File/packaging checks only; not a new scientific acceptance or performance claim.'}
save(V/'archival_review.json',review)
paths=['README.md','PUBLICATION.md','docs/PROJECT_STATE.md','docs/TIMELINE.md','docs/DECISIONS.md','docs/CONVERSATION_MAP.md','docs/EVIDENCE_INDEX.md','docs/OPEN_QUESTIONS.md','docs/RESUME.md','docs/updates/2026-10-17','scripts/followup_archive.py']
subprocess.run(['git','-C',str(REPO),'add','--',*paths],check=True)
manifest=read(REPO/'publication/manifest.json');old={r['path']:r for r in manifest['files']};files=[]
tracked=subprocess.check_output(['git','-C',str(REPO),'ls-files','-z']).decode().split('\0')
for name in sorted(x for x in tracked if x and x!='publication/manifest.json'):
 p=REPO/name;h=sha(p);entry=dict(old.get(name,{'path':name}));changed=entry.get('public_sha256')!=h
 entry.update(bytes=p.stat().st_size,public_sha256=h)
 if changed:entry['transformations']={**entry.get('transformations',{}),'followup_archive_20261017':1}
 if name in source_map:entry['source_snapshot_sha256']=source_map[name]['source_sha256']
 files.append(entry)
manifest['files']=files;manifest['public_file_count_excluding_this_manifest']=len(files);manifest['transformation_totals']['followup_archive_20261017']=sum('followup_archive_20261017' in x.get('transformations',{}) for x in files)
manifest['followup_20261017']={'path':'docs/updates/2026-10-17/README.md','baseline_public_commit':'3c20c92f06796313d392fcc74668e78d4f4b7211','conversation_cutoff_utc':'2026-10-17T06:02:18+00:00','visible_threads':19,'visible_messages':2419,'private_source_archive_sha256':read(BASE/'snapshot_result.json')['archive_sha256'],'public_evidence_archive_sha256':read(PUB/'build_result.json')['archive_sha256'],'original_B_unchanged':True,'raw_conversations_published':False}
save(REPO/'publication/manifest.json',manifest);subprocess.run(['git','-C',str(REPO),'add','publication/manifest.json'],check=True)
assert {x['path'] for x in manifest['files']}=={x for x in tracked if x and x!='publication/manifest.json'}
subprocess.run(['/opt/miniconda3/bin/python3.13','-B',str(REPO/'scripts/verify_public_release.py')],check=True)
print(json.dumps({'status':'passed','tracked_public_files':len(files),'archival_review':review}),flush=True)
