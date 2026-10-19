"""Self-contained, lossless JSON tables for complete MCP results.

No normalization, rounding, sorting of arrays, projections, or omitted defaults.
Every original object is tagged, so user keys cannot collide with codec markers.
References are local to one result and only point to earlier dictionary entries.
"""
from collections import Counter
from copy import deepcopy
import math
from .contracts import encode, digest, strict_json

CODEC = 'harness-tool-json-v2'
LEGEND = ('All Harness results use harness-tool-json-v2: object_schemas contains ordered field names; '
          '{"$":[schema_index,values...]} is one object; {"@":i} expands dictionary[i]. '
          'Dictionary references only point backwards and reset each result. '
          '{"#":[schema_index,row_count,columns]} is an ordered table; each column is a full cell array '
          'or {"=":[default,[[row_index,exception],...]]}. {"!":0} means absent only in table cells; '
          'null is a present null. Ordinary arrays keep their order. Original objects, including marker-like '
          'keys, always use $. The value field is the full result; sha256 hashes the reconstructed canonical JSON. '
          'Every field, number, ID, version and returned entity is preserved; there is no hidden filtering.')


def pack(value):
    counts = Counter()
    def key(v):
        if isinstance(v, (dict, list, str)):
            text = encode(v).decode()
            if len(text) >= 40: return text
        return None
    def scan(v):
        if type(v) not in (dict, list, str, int, float, bool, type(None)):
            raise ValueError('codec accepts only JSON values')
        if isinstance(v, float) and not math.isfinite(v):
            raise ValueError('codec rejects nonfinite numbers')
        if isinstance(v, dict) and not all(type(k) is str for k in v):
            raise ValueError('codec requires string object keys')
        k = key(v)
        if k is not None: counts[k] += 1
        for c in v.values() if isinstance(v, dict) else v if isinstance(v, list) else ():
            scan(c)
    scan(value)
    schemas, schema_ids, refs, ref_ids = [], {}, [], {}
    def schema(fields):
        if fields not in schema_ids:
            schema_ids[fields] = len(schemas)
            schemas.append(list(fields))
        return schema_ids[fields]
    def node(v, skip_ref=False):
        k = key(v)
        if not skip_ref and k is not None and counts[k] > 1:
            if k not in ref_ids:
                encoded = node(v, True)
                ref_ids[k] = len(refs)
                refs.append(encoded)
            return {'@': ref_ids[k]}
        if isinstance(v, dict):
            fields = tuple(sorted(v)); sid = schema(fields)
            return {'$': [sid] + [node(v[f]) for f in fields]}
        if isinstance(v, list) and len(v) > 1 and all(isinstance(c, dict) for c in v):
            fields = tuple(sorted({f for row in v for f in row})); sid = schema(fields)
            columns = []
            for field in fields:
                cells = [node(row[field]) if field in row else {'!': 0} for row in v]
                serialized = [encode(c) for c in cells]
                common = Counter(serialized).most_common(1)[0][0]
                sparse = {'=': [strict_json(common), [[i, c] for i, c in enumerate(cells) if serialized[i] != common]]}
                columns.append(sparse if len(encode(sparse)) < len(encode(cells)) else cells)
            return {'#': [sid, len(v), columns]}
        if isinstance(v, list): return [node(c) for c in v]
        return v
    root = node(value)
    return dict(codec=CODEC, object_schemas=schemas, dictionary=refs, value=root, sha256=digest(value))


def unpack(wire):
    def check(condition):
        if not condition: raise ValueError('invalid lossless tool encoding')
    check(isinstance(wire, dict) and set(wire) == {'codec', 'object_schemas', 'dictionary', 'value', 'sha256'})
    check(wire['codec'] == CODEC)
    schemas, refs = wire['object_schemas'], []
    check(isinstance(schemas, list) and isinstance(wire['dictionary'], list))
    for fields in schemas:
        check(isinstance(fields, list) and all(type(k) is str for k in fields))
        check(len(fields) == len(set(fields)))
    def index(i, length):
        check(type(i) is int and 0 <= i < length)
        return i
    def dec(v):
        if isinstance(v, dict):
            if set(v) == {'@'}: return deepcopy(refs[index(v['@'], len(refs))])
            if set(v) == {'$'}:
                row = v['$']; check(isinstance(row, list) and bool(row))
                fields = schemas[index(row[0], len(schemas))]
                check(len(fields) == len(row)-1)
                return {k: dec(c) for k, c in zip(fields, row[1:])}
            if set(v) == {'#'}:
                table = v['#']; check(isinstance(table, list) and len(table) == 3)
                sid, count, columns = table
                fields = schemas[index(sid, len(schemas))]
                check(type(count) is int and count >= 0 and isinstance(columns, list) and len(fields) == len(columns))
                rows = [{} for _ in range(count)]
                for key, col in zip(fields, columns):
                    if isinstance(col, dict):
                        check(set(col) == {'='} and isinstance(col['='], list) and len(col['=']) == 2)
                        mode, exceptions = col['=']; check(isinstance(exceptions, list))
                        cells = [mode for _ in range(count)]
                        previous = -1
                        for exception in exceptions:
                            check(isinstance(exception, list) and len(exception) == 2)
                            i, cell = exception; index(i, count); check(i > previous)
                            previous = i; cells[i] = cell
                    else: cells = col
                    check(isinstance(cells, list) and len(cells) == count)
                    for row, cell in zip(rows, cells):
                        if cell != {'!': 0}: row[key] = dec(cell)
                return rows
            raise ValueError('unknown lossless tool marker')
        if isinstance(v, list): return [dec(c) for c in v]
        check(type(v) in (str, int, float, bool, type(None)))
        check(not isinstance(v, float) or math.isfinite(v))
        return v
    for value in wire['dictionary']: refs.append(dec(value))
    result = dec(wire['value'])
    check(digest(result) == wire['sha256'])
    return result


def text(value):
    return encode(pack(value)).decode()
