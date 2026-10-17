"""Equivalence and static classification only; never estimate v6 call counts."""
from copy import deepcopy
from .sealed_contexts import classify_sealed_contexts

PHYSICAL={'dispatch','operation_complete','downtime'}

def physical_events(trace, *, start, end):
    return [{k:v for k,v in e.items() if k!='seq'} for e in trace if e['kind'] in PHYSICAL and start<=e['time']<=end]

def equivalence(env, committed, sealed_trace, *, end=1603.10):
    start=env.t;errors=[]
    for event in committed:
        t=event['time']
        if t<start or t>end: continue
        # Original gaps may stop at the same timestamp as the next archived commit.
        while env.t<t:
            before=env.t;env.advance_plan(t)
            if env.t<t and env.t==before:
                return {'valid':False,'errors':['original trigger before archived commit'],'time':env.t}
        env.commit_plan(deepcopy(event['plan']))
    while env.t<end:
        before=env.t;env.advance_plan(end)
        if env.t<end and env.t==before:
            return {'valid':False,'errors':['original trigger before endpoint'],'time':env.t}
    actual=physical_events(env.trace,start=start,end=end)
    expected=physical_events(sealed_trace,start=start,end=end)
    for i in range(max(len(actual),len(expected))):
        if i>=len(actual) or i>=len(expected) or actual[i]!=expected[i]: errors.append({'index':i,'actual':actual[i] if i<len(actual) else None,'expected':expected[i] if i<len(expected) else None})
    return {'valid':not errors,'errors':errors,'time':env.t,'events':len(actual)}
