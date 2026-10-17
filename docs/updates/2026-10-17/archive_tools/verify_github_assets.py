"""Verify the newly uploaded public Release assets using GitHub SHA-256 digests."""
import json,os,subprocess
from pathlib import Path
BASE=Path(__file__).resolve().parents[1];PUB=BASE/'public';REPO='yanaoyong/llm-scheduling-harness-research';RELEASE_ID=415649926
expected=json.loads((PUB/'release_asset_manifest.json').read_text());env=dict(os.environ);env.setdefault('HTTPS_PROXY','http://127.0.0.1:7897')
r=json.loads(subprocess.check_output(['gh','api',f'repos/{REPO}/releases/{RELEASE_ID}'],env=env,timeout=60));assert r['tag_name']=='evidence-20261017-followup-v1'
assets={x['name']:x for x in r['assets']};assert set(assets)=={x['name'] for x in expected['assets']},'Missing or unexpected Release assets'
verified=[]
for e in expected['assets']:
 a=assets[e['name']];assert a['state']=='uploaded',e['name'];assert a['size']==e['bytes'],e['name'];assert a.get('digest')=='sha256:'+e['sha256'],e['name']
 verified.append({'name':e['name'],'asset_id':a['id'],'bytes':a['size'],'sha256':e['sha256'],'github_digest':a['digest']})
report={'status':'passed','repository':REPO,'release_id':RELEASE_ID,'tag':r['tag_name'],'draft_at_verification':r['draft'],'asset_count':len(verified),'all_remote_digests_match':True,'assets':verified,'scope':'GitHub-reported SHA-256 and size match the locally verified upload assets; final publication state is recorded separately.'}
(PUB/'github_assets.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='assets'}))
