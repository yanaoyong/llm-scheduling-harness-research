"""Lossless, deterministic header-once snapshot tables (float precision: 10 digits).

Wire sections have an explicit shape and row count. Cells are JSON values, !
(absent), or Umean~offset / Cconstant distributions. No implicit defaults.
"""
from copy import deepcopy
import json
import math

CURRENT = b'CURRENT\n'


def normalize(value):
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError('non-finite snapshot number')
        return float(format(value, '.10g'))
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    return value


def cell(value):
    if isinstance(value, dict):
        if set(value) == {'type', 'm', 'offset'} and value['type'] == 'uniform':
            return 'U' + cell(value['m']) + '~' + cell(value['offset'])
        if set(value) == {'type', 'c'} and value['type'] == 'constant':
            return 'C' + cell(value['c'])
    return json.dumps(normalize(value), ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def uncell(value):
    if value.startswith('U'):
        m, offset = value[1:].split('~')
        return dict(type='uniform', m=json.loads(m), offset=json.loads(offset))
    if value.startswith('C'):
        return dict(type='constant', c=json.loads(value[1:]))
    return json.loads(value)


def section(name, value):
    """All record lists and record objects use one header, including nested cells."""
    if isinstance(value, dict):
        rows, shape = [value], 'object'
    elif isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
        rows, shape = value, 'table'
    else:
        return '@' + name + '\tvalue\t' + cell(value) + '\n'
    columns = sorted({key for row in rows for key in row})
    lines = ['@' + name + '\t' + shape + '\t' + str(len(rows)) + '\t' + cell(columns)]
    lines.extend('\t'.join(cell(row[k]) if k in row else '!' for k in columns) for row in rows)
    return '\n'.join(lines) + '\n'


def sections(text):
    lines = iter(text.removesuffix('\n').split('\n'))
    result = {}
    for line in lines:
        name, shape, rest = line.split('\t', 2)
        if not name.startswith('@') or name[1:] in result:
            raise ValueError('invalid/duplicate compact section')
        if shape == 'value':
            value = uncell(rest)
        else:
            count, header = rest.split('\t', 1)
            columns = json.loads(header)
            rows = []
            for _ in range(int(count)):
                raw = next(lines)
                cells = raw.split('\t') if columns else []
                if len(cells) != len(columns):
                    raise ValueError('compact table width mismatch')
                rows.append({k: uncell(v) for k, v in zip(columns, cells) if v != '!'})
            if shape not in ('object', 'table') or (shape == 'object' and len(rows) != 1):
                raise ValueError('invalid table shape')
            value = rows[0] if shape == 'object' else rows
        result[name[1:]] = value
    return result


def ranges(ids):
    """Ordered integer ranges; no sorting/deduplication of the original sequence."""
    chunks = []
    for value in ids:
        if chunks and value == chunks[-1][-1] + 1:
            chunks[-1][-1] = value
        else:
            chunks.append([value, value])
    return ','.join(str(a) if a == b else f'{a}:{b}' for a, b in chunks)


def unranges(value):
    out = []
    for part in value.split(',') if value else []:
        bounds = [int(x) for x in part.split(':')]
        out.extend(range(bounds[0], bounds[-1] + 1))
    return out


def encode_prefix(obj):
    routing, machines = obj['routing'], obj['machine_groups']
    result = {k: v for k, v in obj.items() if k not in ('routing', 'machine_groups')}
    if isinstance(routing, dict) and all(isinstance(v, list) and all(isinstance(s, dict) for s in v) for v in routing.values()):
        definitions, keys, routes = [], {}, []
        positional = all(type(s.get('step')) is int and s['step'] == i
                         for steps in routing.values() for i, s in enumerate(steps, 1))
        for route, steps in sorted(routing.items()):
            ids = []
            for step in steps:
                definition = {k: v for k, v in step.items() if k != 'step' or not positional}
                key = cell(definition)
                if key not in keys:
                    keys[key] = len(definitions)
                    definitions.append(definition)
                ids.append(keys[key])
            routes.append(dict(route=route, definitions=ids))
        result.update(step_number_is_position=positional, step_definitions=definitions, routes=routes)
    else:
        result['routing'] = routing
    if isinstance(machines, list) and machines and all(isinstance(m, dict) and type(m.get('id')) is int for m in machines):
        groups = {}
        for index, machine in enumerate(machines):
            attrs = {k: v for k, v in machine.items() if k != 'id'}
            key = cell(attrs)
            if key not in groups:
                groups[key] = dict(attributes=attrs, ids=[], positions=[])
            groups[key]['ids'].append(machine['id'])
            groups[key]['positions'].append(index)
        result['machine_groups_compact'] = [dict(g['attributes'], **{
            '$ids': ranges(g['ids']), '$positions': ranges(g['positions'])}) for g in groups.values()]
    else:
        result['machine_groups'] = machines
    return ('SNAPSHOT_V1\n' + ''.join(section(k, v) for k, v in sorted(result.items()))).encode()


def decode_prefix(payload):
    text = payload.decode() if isinstance(payload, bytes) else payload
    if not text.startswith('SNAPSHOT_V1\n'):
        raise ValueError('unsupported snapshot encoding')
    result = sections(text[len('SNAPSHOT_V1\n'):])
    if 'routes' in result:
        definitions = result.pop('step_definitions')
        positional = result.pop('step_number_is_position')
        result['routing'] = {r['route']: [dict(deepcopy(definitions[d]), **({'step': i} if positional else {}))
                                        for i, d in enumerate(r['definitions'], 1)] for r in result.pop('routes')}
    if 'machine_groups_compact' in result:
        machines = []
        for g in result.pop('machine_groups_compact'):
            attrs = {k: v for k, v in g.items() if k not in ('$ids', '$positions')}
            machines.extend((p, dict(attrs, id=i)) for p, i in zip(unranges(g['$positions']), unranges(g['$ids'])))
        result['machine_groups'] = [m for _, m in sorted(machines)]
    return result


def static_machines(prefix):
    return {m['id']: m for m in prefix['machine_groups']
            if isinstance(m, dict) and 'id' in m}


def encode_current(prefix, current):
    result = deepcopy(current)
    static = static_machines(prefix)
    families = {}
    for mid, m in static.items():
        if 'family' in m:
            families.setdefault(m['family'], []).append(mid)
    family_keys = {cell(sorted(v)): k for k, v in sorted(families.items())}
    eligible_sets, groups = {}, {}
    for index, row in enumerate(result.pop('unreserved_ready')):
        row = dict(row)
        eligible = row.pop('eligible_machines')
        key = cell(eligible)
        # Name the whole family even when the canonical list has a different order.
        family_key = cell(sorted(eligible))
        if family_key in family_keys:
            family = family_keys[family_key]
            ordered = sorted(families[family])
            ref = ['family', family, ranges([ordered.index(mid) for mid in eligible])]
        else:
            if key not in eligible_sets:
                eligible_sets[key] = (len(eligible_sets), eligible)
            ref = ['set', eligible_sets[key][0]]
        oid = row.pop('operation_id')
        row['$eligible'] = ref
        key = cell(row)
        if key not in groups:
            groups[key] = dict(row, **{'$operations': [], '$positions': []})
        groups[key]['$operations'].append(oid)
        groups[key]['$positions'].append(index)
    result['eligible_sets'] = [dict(id=i, machines=ms) for i, ms in eligible_sets.values()]
    result['ready_groups'] = [dict(g, **{'$positions': ranges(g['$positions'])}) for g in groups.values()]
    constants = {}
    machines = result['machines']
    if machines and all('availability_basis' in m and m['availability_basis'] == machines[0].get('availability_basis') for m in machines):
        constants['availability_basis'] = machines[0]['availability_basis']
    inherited = {'family': [], 'cascading': []}
    for m in machines:
        for k in ('family', 'cascading'):
            if k in m and k in static.get(m['machine'], {}) and cell(m[k]) == cell(static[m['machine']][k]):
                del m[k]
                inherited[k].append(m['machine'])
        for k in constants:
            del m[k]
    result['machine_constants'] = constants
    result['machine_inheritance'] = [dict(field=k, machines=ranges(ids)) for k, ids in inherited.items() if ids]
    return CURRENT + ''.join(section(k, v) for k, v in sorted(result.items())).encode()


def decode_snapshot(payload):
    """Return the original canonical prefix/current objects, normalizing floats only."""
    if isinstance(payload, str):
        payload = payload.encode()
    raw_prefix, raw_current = payload.split(CURRENT, 1)
    prefix, current = decode_prefix(raw_prefix), sections(raw_current.decode())
    static = static_machines(prefix)
    families = {}
    for mid, m in static.items():
        if 'family' in m:
            families.setdefault(m['family'], []).append(mid)
    sets = {r['id']: r['machines'] for r in current.pop('eligible_sets')}
    ready = []
    for group in current.pop('ready_groups'):
        group = dict(group)
        reference = group.pop('$eligible')
        kind, ref = reference[:2]
        ids, positions = group.pop('$operations'), unranges(group.pop('$positions'))
        eligible = ([sorted(families[ref])[i] for i in unranges(reference[2])]
                    if kind == 'family' else sets[ref])
        ready.extend((p, dict(deepcopy(group), operation_id=oid, eligible_machines=list(eligible))) for p, oid in zip(positions, ids))
    current['unreserved_ready'] = [r for _, r in sorted(ready)]
    constants = current.pop('machine_constants')
    by_id = {m['machine']: m for m in current['machines']}
    for row in current.pop('machine_inheritance'):
        for mid in unranges(row['machines']):
            by_id[mid][row['field']] = static[mid][row['field']]
    for machine in current['machines']:
        machine.update(constants)
    return prefix, current
