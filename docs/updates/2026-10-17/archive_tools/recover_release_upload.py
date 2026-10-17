"""Retain completed Release parts 005/006; split unfinished 000..004 into 64 MiB pieces."""
import hashlib,json,shutil
from pathlib import Path
BASE=Path(__file__).resolve().parents[1];PUB=BASE/'public';OUT=PUB/'release_assets';OLD=PUB/'superseded_large_parts'
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def main():
 OLD.mkdir(exist_ok=False);shutil.copyfile(PUB/'release_asset_manifest.json',BASE/'review/initial_release_asset_manifest.json')
 for i in range(5):
  p=OUT/f'followup-evidence-20261017.cas.tar.zst.part-{i:03}'
  with p.open('rb') as f:
   for j in range(8):
    raw=f.read(64*1024*1024);assert len(raw)==64*1024*1024;(OUT/(p.name+f'.seg-{j:03}')).write_bytes(raw)
   assert not f.read(1)
  p.rename(OLD/p.name)
 parts=sorted(OUT.glob('*.part-*'));combined=hashlib.sha256()
 for p in parts:
  with p.open('rb') as f:
   for b in iter(lambda:f.read(4*1024*1024),b''):combined.update(b)
 result=json.loads((PUB/'build_result.json').read_text());assert combined.hexdigest()==result['archive_sha256']
 checks=[]
 for p in sorted(OUT.iterdir()):
  if p.name=='checksums.sha256':continue
  checks.append({'name':p.name,'bytes':p.stat().st_size,'sha256':digest(p)})
 (OUT/'checksums.sha256').write_text(''.join(x['sha256']+'  '+x['name']+'\n' for x in checks))
 p=OUT/'checksums.sha256';checks.append({'name':p.name,'bytes':p.stat().st_size,'sha256':digest(p)})
 report={'status':'passed','package_sha256':combined.hexdigest(),'parts':[p.name for p in parts],'assets':checks,'asset_count':len(checks),'recovery':'Unfinished 512 MiB parts split into eight 64 MiB segments; completed parts 005 and 006 retained. Concatenating all .part-* assets lexicographically yields the unchanged verified package.'}
 (PUB/'release_asset_manifest.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'status':'passed','part_count':len(parts),'asset_count':len(checks),'unchanged_archive_sha256':combined.hexdigest()}),flush=True)
if __name__=='__main__':main()
