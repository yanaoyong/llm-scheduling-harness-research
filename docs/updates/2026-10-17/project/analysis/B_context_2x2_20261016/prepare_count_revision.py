from pathlib import Path
O=Path(__file__).resolve().parent;W=O/'workspace/src/smt_fullfab/harness'
def preserve(src,dst):
 assert not dst.exists();dst.write_bytes(src.read_bytes())
preserve(O/'recovery_amendment.json',O/'recovery_amendment_v3.json')
for p in [W/'context_recovery.py',W/'wall_budget.py',O/'experiment.py']:preserve(p,O/(p.stem+'_before_count_revision.py'))
p=W/'context_recovery.py';s=p.read_text().replace('"amendment","transport")','"amendment","transport","wall_budget")').replace('"change_treatments","increase_limits","reset_costs"','"change_treatments","reset_costs"')
s=s.replace('    before=checked_file(value["before_fingerprint"])','    require(grant["increase_limits"] is True and grant["count_caps_removed"] is True and grant["changed_limit_fields"]==["attempts"],"context_count_grant","Only call-count caps removed")\n    before=checked_file(value["before_fingerprint"])')
s=s.replace('row["amendment_sha256"]==digest(revision)','row["amendment_sha256"] in compatible_revision_hashes(reg,revision)')
pos=s.index('\ndef validate_source')
s=s[:pos]+'''
def compatible_revision_hashes(reg,revision):
    from .experiment import checked_file
    allowed={digest(revision)};cursor=revision;seen=set()
    while cursor.get("previous_control_revision"):
        cursor=checked_file(cursor["previous_control_revision"]);h=digest(cursor)
        require(h not in seen and cursor["registration_sha256"]==revision["registration_sha256"],"context_revision_chain","Same registration and acyclic history required")
        seen.add(h)
        if checked_file(cursor["authorization"])["policy"]==POLICY:allowed.add(h)
    return allowed

def apply_count_budget(manifest,row,result):
    from .experiment import registration,checked_file
    require(is_context(manifest),"context_count_marker","Only this four-arm experiment")
    reg=registration(manifest["admission"]);revision=amendment(reg)
    require(revision is not None and row["amendment_sha256"]==digest(revision) and row["run_id"]==manifest["run_id"] and row["original_manifest_sha256"]==digest(manifest) and row["original_attempt_limit"]==manifest["config"]["limits"]["attempts"]==60 and row["effective_attempt_limit"] is None and row["new_model_calls"]==0,"context_count_marker","Exact original run and count-only authorization required")
    result["limits"]["attempts"]=None
    result.update(context_uncapped_counts=True,original_attempt_limit=60,source_revision_sha256=digest(revision))
    return result
''' +s[pos:];p.write_text(s)
p=W/'wall_budget.py';s=p.read_text().replace("    row = markers.get('wall-budget')","    count_row = markers.get('context-uncapped-counts')\n    if count_row is not None:\n        from .context_recovery import apply_count_budget\n        require(set(markers)=={'context-uncapped-counts'}, 'context_count_marker', 'Count-only revision cannot alter time allowances')\n        return apply_count_budget(manifest,count_row,result)\n    row = markers.get('wall-budget')")
s=s.replace("    caps = deepcopy(reg['caps'])\n    for group in ('B3600', 'combined'):\n        caps[group]['wall_seconds'] += budget", "    caps = deepcopy(reg['caps'])\n    if budget.get('context_uncapped_counts'):\n        for group in ('micro', 'combined'):caps[group]['attempts']=None\n    for group in ('B3600', 'combined'):\n        caps[group]['wall_seconds'] += budget")
p.write_text(s)
p=O/'experiment.py';s=p.read_text().replace('require,HarnessError','require,HarnessError,within_cap').replace(" reg_limits=evidence.manifest['config']['limits']"," from src.smt_fullfab.harness.wall_budget import effective_budget\n effective=effective_budget(evidence.manifest,evidence.rows('control_source_revisions'))\n reg_limits=effective['limits']").replace("usage['actual_model_attempts']<=reg_limits['attempts']","within_cap(usage['actual_model_attempts'],reg_limits['attempts'])").replace(" result={'case':case,"," result={'case':case,'effective_limits':reg_limits,'original_limits':evidence.manifest['config']['limits'],")
p.write_text(s)
s=(O/'verify_recovery_uncapped.py').read_text().replace('_v3','_v4')
pos=s.index('fp=fingerprint();')
s=s[:pos]+'''
 def test_count_budget_only_and_shared_caps(self):
  from src.smt_fullfab.harness.wall_budget import effective_budget,shared_caps
  v=View();m=v.manifest;original=deepcopy(m)
  r={'run_id':m['run_id'],'original_manifest_sha256':digest(m),'original_attempt_limit':60,'effective_attempt_limit':None,'new_model_calls':0,'amendment_sha256':digest(revision)}
  self.assertEqual(effective_budget(m,{})['limits']['attempts'],60)
  with patch.object(c,'amendment',return_value=revision):
   b=effective_budget(m,{'context-uncapped-counts':r})
   self.assertIsNone(b['limits']['attempts']);self.assertEqual(m,original)
   self.assertEqual(b['limits'],{**original['config']['limits'],'attempts':None})
   self.assertEqual(b['effective_deadline_epoch'],m['deadline_epoch'])
   caps=shared_caps(reg,b)
   for group in ('micro','combined'):self.assertEqual(caps[group],{**reg['caps'][group],'attempts':None})
   for key,value in [('run_id','wrong'),('amendment_sha256','wrong'),('original_manifest_sha256','wrong'),('effective_attempt_limit',100),('new_model_calls',1)]:
    with self.assertRaises(HarnessError):effective_budget(m,{'context-uncapped-counts':{**r,key:value}})
 def test_prior_same_policy_revision_retains_original_recovery_rows(self):
  from src.smt_fullfab.harness import experiment as ex
  prior={**revision,'authorization':{'x':'grant'}};latest={**revision,'previous_control_revision':{'x':'old'}}
  with patch.object(ex,'checked_file',side_effect=lambda ref:prior if ref['x']=='old' else {'policy':c.POLICY}):
   self.assertIn(digest(prior),c.compatible_revision_hashes(reg,latest))
  with patch.object(ex,'checked_file',side_effect=lambda ref:prior if ref['x']=='old' else {'policy':{'old':'bounded'}}):
   self.assertNotIn(digest(prior),c.compatible_revision_hashes(reg,latest))
''' +s[pos:]
(O/'verify_count_revision.py').write_text(s)
print('Prepared count-only revision; historical v3 files preserved')
