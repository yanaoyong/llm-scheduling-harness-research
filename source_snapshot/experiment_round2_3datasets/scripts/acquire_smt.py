#!/usr/bin/env python3
"""Recover pinned public SMT2020 data and PySCFabSim archive without git credentials."""
import argparse,hashlib,json,subprocess,zipfile,csv,io
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'data/raw/smt'
URLS={
 'SMT2020.zip':'https://p2schedgen.fernuni-hagen.de/fileadmin/ess/uploads_p2schedgen/SMT2020/SMT2020.zip',
 'PySCFabSim-revised-RefactoredVersion2025.zip':'https://zenodo.org/records/15088815/files/david-dd/PySCFabSim-revised-RefactoredVersion2025.zip?download=1',
 'github-release.zip':'https://codeload.github.com/david-dd/PySCFabSim-revised/zip/ae3d55ef08cd0d6bc9cd114eb800e6c920dbede1'}
EXPECTED={'SMT2020.zip':'19c07bfb68cbc5838429531f27d51428155bb11baf58dc79f8caf84b09856872','PySCFabSim-revised-RefactoredVersion2025.zip':'3bf08f4bbc62daad42934022f15546216d5bcd8a8b4e3af9c9028498d9036028','github-release.zip':'12dbe8e63eeff82e13d3cbb2d20a69b2b371004257f7e0c305c12ed7d485505e'}
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def extract_official():
 raw=RAW/'official_dataset2';raw.mkdir(exist_ok=True)
 target=ROOT/'data/smt/SMT2020_LVHM';target.mkdir(parents=True,exist_ok=True)
 prefix='SMT_2020 - Final/AutoSched/dataset 2/LVHM_Model/LVHM_Model.asd/'
 conversion=[]
 with zipfile.ZipFile(RAW/'SMT2020.zip') as z:
  for name in z.namelist():
   if name.endswith('.pdf'):(RAW/Path(name).name).write_bytes(z.read(name))
   if not name.startswith(prefix) or name.endswith('/'):continue
   short=name[len(prefix):];data=z.read(name);(raw/short).write_bytes(data)
   # Keep ALL original Dataset2 files, but normalize only model inputs consumed.
   wanted=short in ['WIP.txt','tool.txt','part.txt','order.txt','attach.txt','downcal.txt','pmcal.txt','fromto.txt','setup.txt','setupgrp.txt'] or short.startswith('route_')
   if not wanted:continue
   encoding='utf-16' if data.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8'
   text=data.decode(encoding).replace('\r\n','\n');outname=short
   text='\n'.join(line for line in text.splitlines() if line.strip('\t '))+'\n'
   if short=='tool.txt':
    rows=list(csv.reader(io.StringIO(text),delimiter='\t'));header=rows[0];combined=[]
    for row in rows[1:]:
     if not any(row):continue
     if row[0]:combined.append(row)
     else:
      for col,value in enumerate(row):
       if value:combined[-1][col]+=(';' if combined[-1][col] else '')+value
    text='\n'.join('\t'.join(row) for row in [header]+combined)+'\n';outname='tool.txt.1l'
   dest=target/outname;dest.write_text(text)
   conversion.append({'source':name,'source_sha256':hashlib.sha256(data).hexdigest(),'output':str(dest.relative_to(ROOT)),'output_sha256':digest(dest),'conversion':'UTF-16 to UTF-8; CRLF to LF; remove all-empty tab rows'+('; collapse tool continuation rank rows with semicolons' if short=='tool.txt' else '')})
 (ROOT/'data/smt/conversion-manifest.json').write_text(json.dumps(conversion,indent=2))
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--proxy',default='http://127.0.0.1:7897');ap.add_argument('--inspect-only',action='store_true');a=ap.parse_args();RAW.mkdir(parents=True,exist_ok=True)
 for name,url in URLS.items():
  p=RAW/name
  if not (p.exists() and zipfile.is_zipfile(p)) and not a.inspect_only:
   cmd=['curl','--proxy',a.proxy,'--location','--fail','--continue-at','-','--max-time','600',url,'-o',str(p)]
   r=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True)
   with (RAW/'acquisition.jsonl').open('a') as f:f.write(json.dumps({'time':datetime.now(timezone.utc).isoformat(),'url':url,'returncode':r.returncode,'stderr':r.stderr})+'\n')
  if p.exists() and zipfile.is_zipfile(p):
   with zipfile.ZipFile(p) as z:
    actual=digest(p)
    if actual!=EXPECTED[name]:raise ValueError('Archive hash differs from frozen source: '+name)
    print(name,p.stat().st_size,actual,len(z.namelist()))
    (RAW/(name+'.contents.json')).write_text(json.dumps(z.namelist(),ensure_ascii=False,indent=2))
  else:print(name,'MISSING_OR_PARTIAL')
 if zipfile.is_zipfile(RAW/'SMT2020.zip'):extract_official()
 if zipfile.is_zipfile(RAW/'github-release.zip'):
  vendor=ROOT/'vendor/PySCFabSim-revised';vendor.mkdir(parents=True,exist_ok=True)
  with zipfile.ZipFile(RAW/'github-release.zip') as z:
   for name in z.namelist():
    if name.endswith('/'):continue
    relative=name.split('/',1)[1]
    if '..' in Path(relative).parts:raise ValueError('unsafe archive path')
    p=vendor/relative;data=z.read(name)
    if p.exists() and p.read_bytes()!=data:raise ValueError('Refusing to overwrite modified vendor '+relative)
    p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
if __name__=='__main__':main()
