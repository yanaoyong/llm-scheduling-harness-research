"""Lossless public-fact tables: preserve all values, identities, and row order."""
from copy import deepcopy
import json

def wire(x): return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()

def flatten(x, path=()):
    if isinstance(x,dict) and x:
        return {p:v for k in sorted(x) for p,v in flatten(x[k],path+(k,)).items()}
    return {path:x}

def pack(x):
    if isinstance(x,dict):
        if '_record_table' in x or '_literal_object' in x:
            return {'_literal_object':[[k,pack(v)] for k,v in x.items()]}
        return {k:pack(v) for k,v in x.items()}
    if not isinstance(x,list): return x
    plain=[pack(v) for v in x]
    if len(x)<2 or not all(isinstance(v,dict) and v for v in x):return plain
    flats=[flatten(v) for v in x];paths=list(flats[0])
    if any(set(f)!=set(paths) for f in flats):
        common=set.intersection(*(set(f) for f in flats))
        constant=[p for p in sorted(common) if all(wire(f[p])==wire(flats[0][p]) for f in flats[1:])]
        layouts=[];rows=[]
        for f in flats:
            layout=[p for p in sorted(f) if p not in constant]
            if layout not in layouts:layouts.append(layout)
            rows.append([layouts.index(layout),[pack(f[p]) for p in layout]])
        table={'_record_table':'lossless-v2','layouts':[[list(p) for p in layout] for layout in layouts],
               'constants':[[list(p),pack(flats[0][p])] for p in constant],
               'rows':rows,'record_count':len(x)}
        return table if len(wire(table))<len(wire(plain)) else plain
    constant=[p for p in paths if all(wire(f[p])==wire(flats[0][p]) for f in flats[1:])]
    columns=[p for p in paths if p not in constant]
    table={'_record_table':'lossless-v1','columns':[list(p) for p in columns],
           'constants':[[list(p),pack(flats[0][p])] for p in constant],
           'rows':[[pack(f[p]) for p in columns] for f in flats], 'record_count':len(x)}
    return table if len(wire(table))<len(wire(plain)) else plain

def unpack(x):
    if isinstance(x,list):return [unpack(v) for v in x]
    if not isinstance(x,dict):return x
    if set(x)=={'_literal_object'}:
        return {k:unpack(v) for k,v in x['_literal_object']}
    if set(x)=={'_record_table','columns','constants','rows','record_count'} and x['_record_table']=='lossless-v1':
        result=[]
        for row in x['rows']:
            d={}
            for path,v in [*x['constants'],*zip(x['columns'],row)]:
                cur=d
                for key in path[:-1]:cur=cur.setdefault(key,{})
                cur[path[-1]]=unpack(deepcopy(v))
            result.append(d)
        return result
    if set(x)=={'_record_table','layouts','constants','rows','record_count'} and x['_record_table']=='lossless-v2':
        result=[]
        for layout_index,values in x['rows']:
            d={}
            for path,v in [*x['constants'],*zip(x['layouts'][layout_index],values)]:
                cur=d
                for key in path[:-1]:cur=cur.setdefault(key,{})
                cur[path[-1]]=unpack(deepcopy(v))
            result.append(d)
        return result
    return {k:unpack(v) for k,v in x.items()}

