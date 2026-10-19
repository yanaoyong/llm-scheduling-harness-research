"""Byte-exact fact reconstruction, including absent/null and hostile marker keys."""
from copy import deepcopy
import math
import random
import pytest
from harness_v6.contracts import encode, strict_json
from harness_v6.tool_codec import pack, unpack, text


def exact(value):
    wire = pack(value)
    assert encode(unpack(strict_json(encode(wire)))) == encode(value)
    assert text(value) == text(deepcopy(value))
    return wire


@pytest.mark.parametrize('value', [None, True, False, 0, 0.0, -0.0, 2**90, 0.12345678901234568,
    '', '中文\t\n"\\', [], {}, [{}, {}], {'$': [0], '@': 0, '#': [0, 1, []], '!': 0, '=': []},
    [{'a': None}, {}, {'a': False}, {'a': 0}, {'a': 0.0}],
    [{'i': i, 'constant': {'long': 'v'*90}, **({'nullable': None} if i % 7 else {})} for i in range(50)],
    {'same': ['x'*80, 'x'*80], 'other': [['x'*80], ['x'*80]]}])
def test_exact_json_types_and_marker_collisions(value):
    exact(value)


def test_seeded_nested_roundtrips():
    rng = random.Random(19378)
    atoms = [None, True, False, 0, -0.0, 2**60, 1.2345678901234567, 'v'*80, '中文', '@', '!']
    def generate(depth):
        if depth == 0 or rng.randrange(3) == 0: return rng.choice(atoms)
        if rng.randrange(2): return [generate(depth-1) for _ in range(rng.randrange(7))]
        return {k: generate(depth-1) for k in rng.sample(['$', '@', '#', '!', '=', 'id', 'value', 'null'], rng.randrange(8))}
    for _ in range(500): exact(generate(4))


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf'), {1: 'not string'}, (1,2)])
def test_non_json_inputs_are_rejected(value):
    with pytest.raises(ValueError): pack(value)


def test_ref_and_hash_tampering_is_rejected():
    base = pack({'a': ['v'*80, 'v'*80]})
    bad = []
    for ref in (-1, True, len(base['dictionary'])):
        w = deepcopy(base); w['value'] = {'@': ref}; bad.append(w)
    w = deepcopy(base); w['dictionary'][0] = {'@': 0}; bad.append(w)
    w = deepcopy(base); w['sha256'] = '0'*64; bad.append(w)
    w = deepcopy(base); w['value'] = {'unexpected': 1}; bad.append(w)
    for wire in bad:
        with pytest.raises(ValueError): unpack(wire)


def test_table_shape_missing_and_sparse_exception_validation():
    value = [{'a': i, **({'b': None} if i % 9 else {})} for i in range(30)]
    base = exact(value)
    assert '#' in base['value']
    assert any(isinstance(c, dict) and '=' in c for c in base['value']['#'][2])
    bad=[]
    w=deepcopy(base); w['value']['#'][1]=True; bad.append(w)
    w=deepcopy(base); w['value']['#'][2][0]=[]; bad.append(w)
    w=deepcopy(base); w['value']['#'][2][0]={'=':[0,[[1,1],[1,2]]]}; bad.append(w)
    w=deepcopy(base); w['value']['#'][2][0]={'=':[0,[[30,1]]]}; bad.append(w)
    w=deepcopy(base); w['object_schemas'][0]=['a','a']; bad.append(w)
    for wire in bad:
        with pytest.raises(ValueError): unpack(wire)
