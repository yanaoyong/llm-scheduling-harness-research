"""Offline checks for the documented Structured Outputs subset.

This checks our deliberately small non-recursive schema vocabulary, not all
JSON Schema. Provider validation remains authoritative. No model call is made.
https://developers.openai.com/api/docs/guides/structured-outputs
"""
from copy import deepcopy
from itertools import combinations


def strict_projection(schema):
    """Preserve optional omission with closed alternatives, never null coercion.

Unique IDs are independently mandatory in plan_delta._ids and validation.
The provider subset lacks uniqueItems; its wire hint becomes a description.
No returned plan is normalized or repaired by this function.
"""
    result = deepcopy(schema)
    if result.pop('uniqueItems', False):
        result['description'] = (result.get('description', '') +
            ' All items must be unique; the host rejects duplicates.').strip()
    if 'minLength' in result:
        minimum = result.pop('minLength')
        if minimum != 1 or 'pattern' in result:
            raise ValueError('unsupported string projection')
        result['pattern'] = r'[\s\S]+'
    if 'items' in result:
        result['items'] = strict_projection(result['items'])
    if 'anyOf' in result:
        result['anyOf'] = [strict_projection(s) for s in result['anyOf']]
    if result.get('type') == 'object':
        properties = {k: strict_projection(v) for k, v in result['properties'].items()}
        required = result['required']
        optional = [k for k in properties if k not in required]
        result['properties'] = properties
        if optional:
            branches = []
            for size in range(len(optional) + 1):
                for included in combinations(optional, size):
                    branch = deepcopy(result)
                    branch['properties'] = {k: v for k, v in properties.items()
                                            if k in required or k in included}
                    branch['required'] = list(branch['properties'])
                    branches.append(branch)
            return {'anyOf': branches}
    return result


def validate_strict_schema(schema):
    """Fail closed before transport on unsupported/ill-formed schema shapes."""
    if not isinstance(schema, dict) or schema.get('type') != 'object' or 'anyOf' in schema:
        raise ValueError('strict schema root must be an object without anyOf')
    totals = dict(properties=0, enum_values=0, string_characters=0, max_depth=0)
    allowed = {'type', 'description', 'properties', 'required', 'additionalProperties',
               'items', 'anyOf', 'enum', 'pattern', 'minItems', 'maxItems',
               'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf'}
    def walk(node, path, depth):
        if not isinstance(node, dict) or not node or set(node) - allowed:
            raise ValueError(f'{path}: empty schema or unsupported keyword')
        if 'anyOf' in node:
            if set(node) - {'anyOf', 'description'} or not isinstance(node['anyOf'], list) or not node['anyOf']:
                raise ValueError(f'{path}: invalid anyOf')
            for index, branch in enumerate(node['anyOf']):
                walk(branch, f'{path}.anyOf[{index}]', depth)
            return
        types = node.get('type')
        types = [types] if isinstance(types, str) else types
        if not isinstance(types, list) or not types or len(types) != len(set(types)) or any(
                t not in {'null', 'string', 'boolean', 'number', 'integer', 'array', 'object'} for t in types):
            raise ValueError(f'{path}: explicit valid type required')
        if 'enum' in node:
            if not isinstance(node['enum'], list) or not node['enum']:
                raise ValueError(f'{path}: invalid enum')
            totals['enum_values'] += len(node['enum'])
            totals['string_characters'] += sum(len(v) for v in node['enum'] if isinstance(v, str))
        if 'object' in types:
            props, required = node.get('properties'), node.get('required')
            if (not isinstance(props, dict) or not isinstance(required, list)
                    or len(required) != len(set(required)) or set(required) != set(props)
                    or node.get('additionalProperties') is not False):
                raise ValueError(f'{path}: closed object requires every property')
            depth += 1
            totals['max_depth'] = max(totals['max_depth'], depth)
            totals['properties'] += len(props)
            totals['string_characters'] += sum(map(len, props))
            for key, child in props.items():
                walk(child, f'{path}.{key}', depth)
        if 'array' in types:
            if 'items' not in node:
                raise ValueError(f'{path}: array missing items')
            walk(node['items'], path + '.items', depth + 1)
    walk(schema, '$', 0)
    for key, limit in [('properties', 5000), ('enum_values', 1000),
                       ('string_characters', 120000), ('max_depth', 10)]:
        if totals[key] > limit:
            raise ValueError(f'strict schema {key} exceeds {limit}')
    return totals
