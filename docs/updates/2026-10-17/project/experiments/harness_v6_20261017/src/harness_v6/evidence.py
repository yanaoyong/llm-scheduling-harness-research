"""Dual-channel provenance: replay the compiler, never trust claimed field sources."""
from .contracts import digest
from .submit import Submitter

def audit_chain(rows):
    errors=[];previous=None
    for i,row in enumerate(rows):
        body={k:v for k,v in row.items() if k!='sha256'}
        if row.get('seq')!=i or row.get('previous')!=previous or digest(body)!=row.get('sha256'):
            errors.append('log_hash_chain')
        if digest(row.get('arguments'))!=row.get('arguments_sha256'): errors.append('argument_hash')
        previous=row.get('sha256')
    return errors

def audit_provenance(rows, calls, submission, initial_state):
    errors=audit_chain(rows)
    logged=[(r['tool'],digest(r['arguments'])) for r in rows]
    observed=[(c['tool'],digest(c['arguments'])) for c in calls]
    if logged!=observed: errors.append('jsonl_mcp_mismatch')
    accepted=[r for r in rows if r['tool']=='submit_plan' and r['result'].get('accepted')]
    if not accepted: return errors+['missing_submit']
    if not submission: return errors+['missing_submission']
    args=submission.get('arguments')
    if not any(r['arguments']==args and r['result']==submission.get('receipt') for r in accepted): errors.append('submission_not_logged')
    replay=Submitter.restore(initial_state)
    try:
        receipt=replay.submit_plan(**args)
        if not receipt['accepted'] or replay.candidate!=submission.get('plan'): errors.append('production_not_from_model')
    except (ValueError,TypeError,KeyError): errors.append('production_not_from_model')
    return errors

def raw_delta(submission):
    return submission['arguments']['delta']
