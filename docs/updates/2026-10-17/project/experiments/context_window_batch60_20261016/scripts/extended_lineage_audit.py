"""Read-only lineage audit with model-proven mutable notes.

Immutable ledgers and source event prefixes remain exact. Notes are reconstructed
from successful raw model actions, as Runtime legitimately replaces notes/current.
"""
from src.smt_fullfab.harness.contracts import require,digest,strict_json
from src.smt_fullfab.harness.evaluation import Evidence
from extended_pilot_support import checkpoint,source_proof


def verify_records(old,ev):
    changes=[]
    for ns,rows in old.value['records'].items():
        if ns=='manifest':continue
        for key,ref in rows.items():
            require(ev.raw(ref)==old.raw(ref),'lineage_object','Inherited object changed')
            current=ev.value['records'].get(ns,{}).get(key)
            if current==ref:continue
            require(ns=='notes' and key=='current','lineage_record','Inherited '+ns+':'+key+' changed')
            expected=old.get(ref);updates=[];previous_index=max(a['index'] for a in old.rows('attempts').values())
            for attempt in sorted(ev.rows('attempts').values(),key=lambda a:a['index']):
                if attempt['index']<=previous_index or attempt['status']!='processed':continue
                try:action=strict_json(ev.raw(attempt['raw_ref']));action=action.get('action',action)
                except (ValueError,TypeError):continue
                result=ev.get(attempt['response_ref']);request=ev.rows('requests').get(action.get('request_id'))
                if request and request['attempt_id']!=attempt['attempt_id']:continue
                if action.get('tool')=='apply_candidate' and result.get('status')=='accepted' and result.get('selection_note_status')=='saved':
                    expected={'version':expected['version']+1,'text':action['selection_note'],
                              'authority':'model_notes_only','attempt_id':attempt['attempt_id']}
                elif action.get('tool')=='write_notes' and result.get('status')=='ok':
                    require(action['expected_version']==expected['version'],'lineage_notes','Note version gap')
                    expected={'version':expected['version']+1,'text':action['text'],'authority':'model_notes_only'}
                else:continue
                updates.append(attempt['attempt_id'])
            require(current is not None and ev.get(current)==expected,'lineage_notes','Notes differ from successful raw model actions')
            changes.append({'record':'notes/current','model_updates':updates,'old_version':old.get(ref)['version'],'new_version':expected['version']})
    return changes


def verify_inheritance(ev):
    marker=ev.rows('observation_extensions')['882_to_1800'];entry=marker['predecessor']
    old=Evidence(entry['directory'],entry['evidence_sha256']);state,trace,suffix=checkpoint(old)
    require(ev.value['events'][:len(old.value['events'])]==old.value['events'],'extension_audit','Original events changed')
    require(ev.value['physical'][:len(trace)]==old.value['physical'][:len(trace)],'extension_audit','Original physical prefix changed')
    require(marker['omitted_cutoff_presentation']==suffix and marker['checkpoint_state_sha256']==digest(state)
            and marker['retained_trace_sha256']==digest(trace),'extension_audit','Checkpoint proof changed')
    notes=verify_records(old,ev)
    require(ev.manifest['run_id']==old.manifest['run_id'] and
            all(ev.manifest[k]==old.manifest[k] for k in ('created_epoch','initial_state_sha256',
                'initial_trace_sha256','start_time','end_time','period_anchor','prefix_events','parent')),
            'extension_audit','Original identity or clock changed')
    return {'valid':True,'inherited_calls':4,'inherited_commits':len(old.rows('commits')),
            'physical_prefix_events':len(trace),'omitted_presentation_events':len(suffix),
            'production_decisions_changed':False,'source_changed_files':source_proof(old,ev.manifest['fingerprint']),
            'legitimate_model_note_updates':notes,'immutable_ledgers_exact':True}
