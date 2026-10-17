"""Resume only absent verified-public Release assets; never overwrite matching evidence."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import json,os,subprocess,time
BASE=Path(__file__).resolve().parents[1];PUB=BASE/'public';OUT=PUB/'release_assets';REPO='yanaoyong/llm-scheduling-harness-research';TAG='evidence-20261017-followup-v1';RID=415649926
expected={x['name']:x for x in json.loads((PUB/'release_asset_manifest.json').read_text())['assets']};env=dict(os.environ)
for k in ['HTTPS_PROXY','HTTP_PROXY','ALL_PROXY','https_proxy','http_proxy','all_proxy']:env.pop(k,None)
env['GODEBUG']='http2client=0'
def snapshot():
 r=json.loads(subprocess.check_output(['gh','api',f'repos/{REPO}/releases/{RID}'],env=env,timeout=60));assets={a['name']:a for a in r['assets']};assert not set(assets)-set(expected),'Unexpected asset requires review'
 for name,a in assets.items():
  e=expected[name];assert a['state']=='uploaded' and a['size']==e['bytes'] and a.get('digest')=='sha256:'+e['sha256'],'Existing asset does not match: '+name
 return assets
def upload(name):
 try:
  p=subprocess.run(['gh','release','upload',TAG,'--repo',REPO,str(OUT/name)],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=600)
  return {'name':name,'returncode':p.returncode,'output':p.stdout[-2000:]}
 except subprocess.TimeoutExpired:return {'name':name,'returncode':'timeout','output':'Will re-read remote state before any further upload.'}
results=[]
for attempt in range(1,6):
 existing=snapshot();missing=sorted(set(expected)-set(existing));print(json.dumps({'stage':'remote_check','round':attempt,'verified_assets':len(existing),'expected':len(expected),'missing':len(missing)}),flush=True)
 if not missing:break
 with ThreadPoolExecutor(max_workers=3) as pool:
  pending={pool.submit(upload,name):name for name in missing}
  for fut in as_completed(pending):
   row=fut.result();row['round']=attempt;results.append(row);print(json.dumps({'stage':'upload','name':row['name'],'returncode':row['returncode']}),flush=True)
 (BASE/'review/upload_missing_attempts.json').write_text(json.dumps(results,indent=2)+'\n')
assert len(snapshot())==len(expected),'Some assets remain incomplete after bounded upload attempts'
print(json.dumps({'status':'passed','verified_assets':len(expected)}),flush=True)
