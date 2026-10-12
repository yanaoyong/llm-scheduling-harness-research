"""Lossless compact observation paging and exact choice decoding.

Content dictionaries and source ordinals preserve every JSON field and array order.
No score, rank, preferred machine, scheduling selection or fallback is computed.
"""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json

MACHINE_FIELDS=['machine','available_at','current_setup','min_left','min_setup','cascading','processing_until','unavailable_intervals']
TYPE_FIELDS=['batch_key','processing_seconds','occupation_seconds','transport_seconds','batch_min','batch_max','setup','setup_time','terminal']
OP_FIELDS=['operation_id','type_index','release_time','predecessor_ids','priority','due','remaining_work_seconds','eligible_override']
MACHINE_ROW_FIELDS=MACHINE_FIELDS+['source_index','machine_extras_index']
OP_ROW_FIELDS=OP_FIELDS+['source_index','lot_id','step','visit','waiting_since','operation_extras_index']
_OP_CORE=['operation_id','release_time','predecessor_ids','priority','due','remaining_work_seconds','eligible_machines','lot_id','step','visit','waiting_since']
_ALL_FAMILY='all_family_machines'


def _canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def _source_digest(problem):
    return hashlib.sha256(_canonical(problem).encode('utf-8')).hexdigest()


def _intern(value,table,index):
    key=_canonical(value)
    if key not in index:
        index[key]=len(table);table.append(deepcopy(value))
    return index[key]


def _extra(source,encoded):
    # The separate absent list preserves missing keys versus explicit JSON null.
    return {'values':{k:v for k,v in source.items() if k not in encoded},
            'absent':[k for k in encoded if k not in source]}


def compact_pages(problem,max_chars=75000):
    """Encode the complete observation, without filtering or ranking any row.

    max_chars bounds each serialized page, not the enclosing model prompt.
    An indivisible catalog/row that cannot fit raises instead of truncating.
    """
    if type(max_chars) is not int or max_chars<2:
        raise ValueError('max_chars must be an integer >= 2')
    machines=defaultdict(list);operations=defaultdict(list)
    for i,m in enumerate(problem['machines']):
        m['machine']  # Required structural identity; no inferred identifiers.
        machines[m['family']].append((i,m))
    for i,o in enumerate(problem['operations']):
        o['operation_id']
        operations[o['family']].append((i,o))
    groups=[]
    for family in sorted(set(machines)|set(operations)):
        types=[];type_map={};rows=[];machine_rows=[]
        machine_extras=[];machine_extra_map={};operation_extras=[];operation_extra_map={}
        mids=sorted(m['machine'] for _,m in machines[family])
        for i,m in machines[family]:
            ei=_intern(_extra(m,MACHINE_FIELDS+['family']),machine_extras,machine_extra_map)
            machine_rows.append([m.get(k) for k in MACHINE_FIELDS]+[i,ei])
        for i,op in operations[family]:
            ti=_intern([op.get(k) for k in TYPE_FIELDS],types,type_map)
            eligible=op.get('eligible_machines')
            if eligible==_ALL_FAMILY:
                raise ValueError('eligible_machines must not use the reserved paging sentinel')
            eligibility=_ALL_FAMILY if _canonical(eligible)==_canonical(mids) else eligible
            ei=_intern(_extra(op,_OP_CORE+TYPE_FIELDS+['family']),operation_extras,operation_extra_map)
            rows.append([op['operation_id'],ti,op.get('release_time'),op.get('predecessor_ids'),
                         op.get('priority'),op.get('due'),op.get('remaining_work_seconds'),eligibility,
                         i,op.get('lot_id'),op.get('step'),op.get('visit'),op.get('waiting_since'),ei])
        groups.append({'family':family,'machines':machine_rows,'types':types,'operations':rows,
                       'machine_extras':machine_extras,'operation_extras':operation_extras})
    # Page accounting uses the same ASCII-escaped compact JSON used by prompts.
    size=lambda value:len(json.dumps(value,separators=(',',':'),allow_nan=False))
    pages=[];page=[]
    for group in groups:
        if size([group])>max_chars:
            if page:pages.append(page);page=[]
            base={k:v for k,v in group.items() if k!='operations'};chunk=[]
            if not group['operations'] or size([{**base,'operations':[]}])>max_chars:
                raise ValueError('family catalog exceeds page character limit')
            for row in group['operations']:
                if size([{**base,'operations':[row]}])>max_chars:
                    raise ValueError('single operation and family catalog exceed page character limit')
                if chunk and size([{**base,'operations':chunk+[row]}])>max_chars:
                    pages.append([{**base,'operations':chunk}]);chunk=[]
                chunk.append(row)
            if chunk:pages.append([{**base,'operations':chunk}])
        else:
            if page and size(page+[group])>max_chars:pages.append(page);page=[]
            page.append(group)
    if page:pages.append(page)
    metadata={k:deepcopy(v) for k,v in problem.items() if k not in ('machines','operations')}
    result={'schema':'fullfab-compact-paging-v2','problem_metadata':metadata,
            'source_problem_sha256':_source_digest(problem),
            'machine_fields':list(MACHINE_ROW_FIELDS),'type_fields':list(TYPE_FIELDS),'operation_fields':list(OP_ROW_FIELDS),
            'operation_identity':'lot_id, step and visit are explicit columns; operation_id is never parsed',
            'eligible_override_sentinel':_ALL_FAMILY,
            'dictionary_semantics':'extras.values restores every unencoded field; extras.absent removes missing encoded fields; source_index restores original array order',
            'pages':[deepcopy(page) for page in pages],'machine_count':len(problem['machines']),
            'operation_count':len(problem['operations']),'page_count':len(pages)}
    # Existing controller metadata readers can continue using these exact mirrors.
    for key in ('time','horizon_end','scope','setup_transitions','min_runs'):
        if key in problem:result[key]=deepcopy(problem[key])
    return result


def expand_pages(manifest,pages=None):
    """Reconstruct and verify complete v2 JSON, including unknown future fields.

    This is a generic round-trip checker. Independent audits should implement
    their own inverse from the published schema, rather than project core keys.
    """
    if manifest.get('schema')!='fullfab-compact-paging-v2':
        raise ValueError('complete observation reconstruction requires compact v2')
    if (manifest.get('machine_fields')!=MACHINE_ROW_FIELDS or manifest.get('type_fields')!=TYPE_FIELDS
            or manifest.get('operation_fields')!=OP_ROW_FIELDS
            or manifest.get('eligible_override_sentinel')!=_ALL_FAMILY):
        raise ValueError('unknown compact v2 field schema')
    pages=manifest['pages'] if pages is None else pages
    for key in ('machine_count','operation_count','page_count'):
        if type(manifest.get(key)) is not int or manifest[key]<0:raise ValueError('invalid row/page count')
    if manifest.get('page_count')!=len(pages):raise ValueError('page count mismatch')
    problem=deepcopy(manifest['problem_metadata'])
    if 'machines' in problem or 'operations' in problem:raise ValueError('metadata contains row arrays')
    for key in ('time','horizon_end','scope','setup_transitions','min_runs'):
        if (key in manifest)!=(key in problem) or (key in problem and _canonical(manifest[key])!=_canonical(problem[key])):
            raise ValueError('metadata mirror mismatch: '+key)
    machine_rows={};operation_rows={};family_catalogs={};used={};catalog_lengths={}

    def index(value,size):
        if type(value) is not int or not 0<=value<size:raise ValueError('invalid dictionary/source index')
        return value

    def restore(core,extra,encoded):
        if set(extra)!={'values','absent'} or not isinstance(extra['values'],dict) or not isinstance(extra['absent'],list):
            raise ValueError('invalid extras entry')
        absent=extra['absent']
        if len(set(absent))!=len(absent) or set(absent)-set(encoded):raise ValueError('invalid missing-field list')
        if set(extra['values'])&set(encoded):raise ValueError('extras overwrite an encoded field')
        for key in absent:core.pop(key,None)
        core.update(deepcopy(extra['values']))
        return core

    for page in pages:
        for group in page:
            if set(group)!={'family','machines','types','operations','machine_extras','operation_extras'}:
                raise ValueError('invalid family group fields')
            family=group['family']
            catalog=_canonical({k:v for k,v in group.items() if k!='operations'})
            if family in family_catalogs and family_catalogs[family]!=catalog:
                raise ValueError('split family catalogs differ')
            family_catalogs[family]=catalog
            used.setdefault(family,{'types':set(),'machine_extras':set(),'operation_extras':set()})
            catalog_lengths[family]={key:len(group[key]) for key in used[family]}
            mids=sorted(row[0] for row in group['machines'])
            local_machines=set()
            for row in group['machines']:
                if len(row)!=len(MACHINE_ROW_FIELDS):raise ValueError('machine row width mismatch')
                source=index(row[8],manifest['machine_count'])
                if source in local_machines:raise ValueError('duplicate machine in family catalog')
                local_machines.add(source)
                ei=index(row[9],len(group['machine_extras']));used[family]['machine_extras'].add(ei)
                extra=group['machine_extras'][ei]
                decoded=restore({**dict(zip(MACHINE_FIELDS,row[:8])),'family':family},extra,MACHINE_FIELDS+['family'])
                if source in machine_rows and _canonical(machine_rows[source])!=_canonical(decoded):
                    raise ValueError('conflicting repeated machine')
                machine_rows[source]=decoded
            for row in group['operations']:
                if len(row)!=len(OP_ROW_FIELDS):raise ValueError('operation row width mismatch')
                source=index(row[8],manifest['operation_count'])
                if source in operation_rows:raise ValueError('duplicate operation source index')
                ti=index(row[1],len(group['types']));used[family]['types'].add(ti)
                tp=group['types'][ti]
                if len(tp)!=len(TYPE_FIELDS):raise ValueError('type row width mismatch')
                ei=index(row[13],len(group['operation_extras']));used[family]['operation_extras'].add(ei)
                extra=group['operation_extras'][ei]
                eligible=mids if row[7]==_ALL_FAMILY else deepcopy(row[7])
                core={'family':family,'operation_id':row[0],'release_time':row[2],'predecessor_ids':row[3],
                      'priority':row[4],'due':row[5],'remaining_work_seconds':row[6],'eligible_machines':eligible,
                      'lot_id':row[9],'step':row[10],'visit':row[11],'waiting_since':row[12],**dict(zip(TYPE_FIELDS,tp))}
                operation_rows[source]=restore(core,extra,_OP_CORE+TYPE_FIELDS+['family'])
    for family,references in used.items():
        if any(indices!=set(range(catalog_lengths[family][key])) for key,indices in references.items()):
            raise ValueError('unreferenced family dictionary entry')
    if set(machine_rows)!=set(range(manifest['machine_count'])) or set(operation_rows)!=set(range(manifest['operation_count'])):
        raise ValueError('missing source rows')
    problem['machines']=[machine_rows[i] for i in range(manifest['machine_count'])]
    problem['operations']=[operation_rows[i] for i in range(manifest['operation_count'])]
    if _source_digest(problem)!=manifest.get('source_problem_sha256'):
        raise ValueError('complete source observation digest mismatch')
    return problem


def decode_plan(problem,output,*,version,valid_until=None):
    """Translate exact model choices, preserving output order and chosen times."""
    ops={o['operation_id']:o for o in problem['operations']}
    tasks=[]
    for i,task in enumerate(output['tasks']):
        chosen=[ops[oid] for oid in task['operations']]
        if not chosen:raise ValueError('empty task')
        tasks.append({'id':str(i),'machine':task['machine'],'lot_ids':[o['lot_id'] for o in chosen],
                      'steps':[o['step'] for o in chosen],'visits':[o['visit'] for o in chosen],
                      'operation_ids':list(task['operations']),'not_before':task['start']})
    holds=[]
    for h in output.get('holds',[]):
        hold={k:v for k,v in h.items() if k!='after_sequence'}
        if h.get('after_sequence') is not None:
            index=next((i for i,t in enumerate(output['tasks']) if t['machine']==h['machine'] and t.get('sequence')==h['after_sequence']),None)
            if index is None:raise ValueError('hold after_sequence not in model chosen tasks')
            hold['after_task_id']=str(index)
        holds.append(hold)
    return {'version':str(version),'created_at':problem['time'],
            'valid_until':problem['horizon_end'] if valid_until is None else valid_until,
            'freeze_until':problem['time'],'reason':output['reason'],'scope':problem['scope'],
            'tasks':tasks,'holds':holds}


def validate_choices(problem,tasks):
    """Read-only exact feasibility checks. Never repair or choose alternatives."""
    ops={o['operation_id']:o for o in problem['operations']};seen=set()
    for t in tasks:
        if type(t['machine']) is not int or type(t['start']) not in (int,float) or t['start']<problem['time']:
            raise ValueError('invalid machine/start')
        chosen=[ops[oid] for oid in t['operations']]
        if not chosen:raise ValueError('empty batch')
        for o in chosen:
            if o['operation_id'] in seen:raise ValueError('duplicate operation')
            seen.add(o['operation_id'])
            if t['machine'] not in o['eligible_machines']:raise ValueError('ineligible explicit machine')
            if o['batch_key']!=chosen[0]['batch_key']:raise ValueError('incompatible batch')
        if not chosen[0]['batch_min']<=len(chosen)<=chosen[0]['batch_max']:raise ValueError('batch min/max')
    return {'valid':True,'explicit_operations':len(seen),'tasks':len(tasks)}
