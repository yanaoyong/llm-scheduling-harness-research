"""Split the verified public evidence package and checksum every Release asset."""
import hashlib,json,shutil
from pathlib import Path
BASE=Path(__file__).resolve().parents[1];PUB=BASE/'public';OUT=PUB/'release_assets'
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def main():
 result=json.loads((PUB/'build_result.json').read_text());assert result['status']=='passed'
 for name in ['privacy_review.json','public_package_verification.json','restore_smoke.json']:assert json.loads((PUB/name).read_text())['status']=='passed'
 OUT.mkdir(exist_ok=False);source=PUB/result['archive'];total=hashlib.sha256();parts=[]
 with source.open('rb') as f:
  part=0
  while True:
   first=f.read(4*1024*1024)
   if not first:break
   p=OUT/(source.name+f'.part-{part:03}');part+=1;written=0
   with p.open('xb') as out:
    b=first
    while b:
     out.write(b);total.update(b);written+=len(b)
     if written==512*1024*1024:break
     b=f.read(min(4*1024*1024,512*1024*1024-written))
   parts.append(p.name)
 assert total.hexdigest()==result['archive_sha256']
 for name in ['followup_archive.py','README.md','build_result.json','selection.json','privacy_review.json','public_package_verification.json','restore_smoke.json']:shutil.copyfile(PUB/name,OUT/name)
 (OUT/'archive-checksum.sha256').write_text(result['archive_sha256']+'  '+source.name+'\n')
 checks=[]
 for p in sorted(OUT.iterdir()):checks.append({'name':p.name,'bytes':p.stat().st_size,'sha256':digest(p)})
 (OUT/'checksums.sha256').write_text(''.join(x['sha256']+'  '+x['name']+'\n' for x in checks))
 p=OUT/'checksums.sha256';checks.append({'name':p.name,'bytes':p.stat().st_size,'sha256':digest(p)})
 report={'status':'passed','package_sha256':total.hexdigest(),'parts':parts,'assets':checks,'asset_count':len(checks)}
 (PUB/'release_asset_manifest.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'status':'passed','part_count':len(parts),'asset_count':len(checks),'package_bytes':result['compressed_bytes']}),flush=True)
if __name__=='__main__':main()
