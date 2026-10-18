"""Lossless, deterministic header-once snapshot tables (float precision: 10 digits).

Wire sections have an explicit shape and row count. Cells are JSON values, !
(absent), or Umean~offset / Cconstant distributions. No implicit defaults.
"""
from copy import deepcopy
import json
import math
import re
from collections import Counter

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



def check_format(snapshot_format):
    if snapshot_format not in ('explicit', 'dense'):
        raise ValueError('snapshot_format must be explicit or dense')
    return snapshot_format


def dense_cell(value):
    if isinstance(value, str) and value and not any(c in value for c in '\t\n\r') and value[0] not in '!=$@UC"[{':
        try:
            json.loads(value)
        except (ValueError, TypeError):
            # Numeric-looking strings, including non-JSON numeric spellings, stay quoted.
            if not re.match(r'^[+\-.0-9]', value) and value.strip() == value:
                return value
    return cell(value)


def dense_uncell(value):
    try:
        return uncell(value)
    except (ValueError, TypeError):
        return value


def token_cost(text):
    """Fixed stdlib token proxy; independent of optional tokenizer installation."""
    return len(re.findall(r'\w{1,4}|[^\w\s]|[\t\n]', text))


def dense_section(name, value, token_counter=token_cost):
    if isinstance(value, dict):
        rows, shape = [value], 'object'
    elif isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
        rows, shape = value, 'table'
    else:
        return '@' + name + '\tvalue\t' + cell(value) + '\n'
    columns = sorted({k for row in rows for k in row})
    defaults, aliases = {}, {}
    encoded = [[dense_cell(row[k]) if k in row else '!' for k in columns] for row in rows]
    def render():
        header = '@' + name + '\t' + shape + '\t' + str(len(rows)) + '\t' + cell(columns)
        header += '\tdefaults ' + cell(defaults) + '\tequals ' + cell(aliases)
        return header + '\n' + '\n'.join('\t'.join(row) for row in encoded) + '\n'
    for target, source, wrap in [('cadence', 'processing', False), ('processing_until', 'available_at', True)]:
        if target not in columns or source not in columns:
            continue
        i = columns.index(target)
        matches = [n for n, row in enumerate(rows) if target in row and source in row and
                   cell(row[target]) == cell([row[source]] if wrap else row[source])]
        before = token_counter(render())
        saved = [encoded[n][i] for n in matches]
        aliases[target] = [source] if wrap else source
        for n in matches:
            encoded[n][i] = '='
        if token_counter(render()) >= before:
            del aliases[target]
            for n, old in zip(matches, saved):
                encoded[n][i] = old
    for i, key in enumerate(columns):
        # Mode is over the entire present column, including aliased values.
        counts = Counter(cell(row[key]) for row in rows if key in row)
        if not counts:
            continue
        winner = min(counts, key=lambda x: (-counts[x], x))
        matches = [n for n, row in enumerate(rows) if key in row and cell(row[key]) == winner and encoded[n][i] != '=']
        before = token_counter(render())
        saved = [encoded[n][i] for n in matches]
        defaults[key] = uncell(winner)
        for n in matches:
            encoded[n][i] = ''
        if token_counter(render()) >= before:
            del defaults[key]
            for n, old in zip(matches, saved):
                encoded[n][i] = old
    return render()


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
            parts = header.split('\t')
            columns = json.loads(parts[0])
            dense = len(parts) > 1
            defaults = json.loads(parts[1].removeprefix('defaults ')) if dense else {}
            aliases = json.loads(parts[2].removeprefix('equals ')) if dense else {}
            rows = []
            for _ in range(int(count)):
                raw = next(lines)
                cells = raw.split('\t') if columns else []
                if len(cells) != len(columns):
                    raise ValueError('compact table width mismatch')
                row = {k: deepcopy(defaults[k]) if v == '' and dense else (dense_uncell(v) if dense else uncell(v))
                       for k, v in zip(columns, cells) if v != '!' and not (dense and v == '=')}
                for k, v in zip(columns, cells):
                    if dense and v == '=':
                        source = aliases[k]
                        row[k] = [deepcopy(row[source[0]])] if isinstance(source, list) else deepcopy(row[source])
                rows.append(row)
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


def encode_prefix(obj, snapshot_format="explicit", token_counter=token_cost):
    check_format(snapshot_format)
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
        for machine in sorted(machines, key=lambda m: m['id']):
            attrs = {k: v for k, v in machine.items() if k != 'id'}
            key = cell(attrs)
            if key not in groups:
                groups[key] = dict(attributes=attrs, ids=[])
            groups[key]['ids'].append(machine['id'])
        result['machine_groups_compact'] = [dict(g['attributes'], **{
            '$ids': ranges(g['ids'])}) for g in groups.values()]
    else:
        result['machine_groups'] = machines
    writer = (lambda k, v: dense_section(k, v, token_counter)) if snapshot_format == 'dense' else section
    magic = 'SNAPSHOT_V1_DENSE' if snapshot_format == 'dense' else 'SNAPSHOT_V1'
    return (magic + '\n' + ''.join(writer(k, v) for k, v in sorted(result.items()))).encode()


def decode_prefix(payload):
    text = payload.decode() if isinstance(payload, bytes) else payload
    if text.split('\n', 1)[0] not in ('SNAPSHOT_V1', 'SNAPSHOT_V1_DENSE'):
        raise ValueError('unsupported snapshot encoding')
    result = sections(text.split('\n', 1)[1])
    if 'routes' in result:
        definitions = result.pop('step_definitions')
        positional = result.pop('step_number_is_position')
        result['routing'] = {r['route']: [dict(deepcopy(definitions[d]), **({'step': i} if positional else {}))
                                        for i, d in enumerate(r['definitions'], 1)] for r in result.pop('routes')}
    if 'machine_groups_compact' in result:
        machines = []
        for g in result.pop('machine_groups_compact'):
            attrs = {k: v for k, v in g.items() if k != '$ids'}
            machines.extend(dict(attrs, id=i) for i in unranges(g['$ids']))
        result['machine_groups'] = sorted(machines, key=lambda m: m['id'])
    return result


def static_machines(prefix):
    return {m['id']: m for m in prefix['machine_groups']
            if isinstance(m, dict) and 'id' in m}


def encode_current(prefix, current, snapshot_format="explicit", token_counter=token_cost):
    check_format(snapshot_format)
    result = deepcopy(current)
    static = static_machines(prefix)
    families = {}
    for mid, m in static.items():
        if 'family' in m:
            families.setdefault(m['family'], []).append(mid)
    family_keys = {cell(sorted(v)): k for k, v in sorted(families.items())}
    eligible_sets, groups = {}, {}
    for row in sorted(result.pop('unreserved_ready'), key=lambda r: r['operation_id']):
        row = dict(row)
        eligible = row.pop('eligible_machines')
        key = cell(eligible)
        if key in family_keys:
            ref = ['family', family_keys[key]]
        else:
            if key not in eligible_sets:
                eligible_sets[key] = (len(eligible_sets), eligible)
            ref = ['set', eligible_sets[key][0]]
        oid = row.pop('operation_id')
        if snapshot_format == 'dense' and 'release_time' in row and 'time' in current and cell(row['release_time']) == cell(current['time']):
            del row['release_time']
            row['$release_time_is_time'] = True
        row['$eligible'] = ref
        key = cell(row)
        if key not in groups:
            groups[key] = dict(row, **{'$operations': []})
        groups[key]['$operations'].append(oid)
    result['eligible_sets'] = [dict(id=i, machines=ms) for i, ms in eligible_sets.values()]
    result['ready_groups'] = list(groups.values())
    constants = {}
    machines = result['machines'] = sorted(result['machines'], key=lambda m: m['machine'])
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
    writer = (lambda k, v: dense_section(k, v, token_counter)) if snapshot_format == 'dense' else section
    return CURRENT + ''.join(writer(k, v) for k, v in sorted(result.items())).encode()


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
        if group.pop('$release_time_is_time', False):
            group['release_time'] = current['time']
        reference = group.pop('$eligible')
        kind, ref = reference
        ids = group.pop('$operations')
        eligible = sorted(families[ref]) if kind == 'family' else sets[ref]
        ready.extend(dict(deepcopy(group), operation_id=oid, eligible_machines=list(eligible)) for oid in ids)
    current['unreserved_ready'] = sorted(ready, key=lambda r: r['operation_id'])
    current['machines'].sort(key=lambda m: m['machine'])
    constants = current.pop('machine_constants')
    by_id = {m['machine']: m for m in current['machines']}
    for row in current.pop('machine_inheritance'):
        for mid in unranges(row['machines']):
            by_id[mid][row['field']] = static[mid][row['field']]
    for machine in current['machines']:
        machine.update(constants)
    return prefix, current
