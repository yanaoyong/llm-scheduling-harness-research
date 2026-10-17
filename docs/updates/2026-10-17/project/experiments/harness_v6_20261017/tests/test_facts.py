import unittest
from harness_v6.contracts import HarnessError
from harness_v6.facts import FactReader, build_facts

class FactTests(unittest.TestCase):
    def test_T11_filtered_pages_exact_complete_source_order_and_cursor_binding(self):
        operations = [{'operation_id': 'op-' + str(i), 'family': 'F' if i % 2 else 'G',
                       'eligible_machines': [2, 3] if i % 4 else [4], 'conditional': i % 3 == 0,
                       **({'nullable': None} if i % 5 else {})} for i in range(1103)]
        facts = build_facts({'machines': [], 'operations': operations}, {'tasks': [], 'holds': []})
        reader = FactReader('owned-context', facts)
        where = [{'field': 'eligible_machines', 'op': 'contains', 'value': 2}, {'field': 'conditional', 'op': 'eq', 'value': False}]
        expected = [v for v in operations if 2 in v['eligible_machines'] and not v['conditional']]
        cursor, found, saved = None, [], None
        while True:
            result = reader.read({'kind': 'operations', 'where': where, 'cursor': cursor, 'count': 73,
                                  'fields': ['operation_id', 'nullable', 'absent']})
            self.assertEqual(result['catalog_total'], len(operations))
            self.assertEqual(result['matching_total'], len(expected))
            for row in result['entities']:
                self.assertIn('absent', row['absent_fields'])
                self.assertEqual('nullable' in row['absent_fields'], row['source_index'] % 5 == 0)
                found.append(row['value']['operation_id'])
            cursor = result['next_cursor']
            if cursor and saved is None: saved = cursor
            if cursor is None: break
        self.assertEqual(found, [v['operation_id'] for v in expected])
        with self.assertRaisesRegex(HarnessError, 'stale_cursor'):
            reader.read({'kind': 'operations', 'where': where[:1], 'cursor': saved, 'count': 1})
        with self.assertRaisesRegex(HarnessError, 'stale_cursor'):
            FactReader('new-context', facts).read({'kind': 'operations', 'where': where, 'cursor': saved, 'count': 1})
        result = reader.read({'kind': 'operations', 'where': [{'field': 'nullable', 'op': 'eq', 'value': None}], 'cursor': None, 'count': 512})
        self.assertTrue(all('nullable' in row['value'] for row in result['entities']))
        result = reader.read({'kind': 'operations', 'where': [{'field': 'conditional', 'op': 'eq', 'value': 0}], 'cursor': None, 'count': 1})
        self.assertEqual(result['matching_total'], 0)  # false is not numeric zero
        for predicate in ({'field': 'private_rng', 'op': 'eq', 'value': 1}, {'field': 'family', 'op': 'rank_best', 'value': 'F'}):
            with self.assertRaisesRegex(HarnessError, 'query_filter'):
                reader.read({'kind': 'operations', 'where': [predicate], 'cursor': None, 'count': 1})


from copy import deepcopy
import pytest
from harness_v6.facts import reconstruct, changes, apply_changes
from harness_v6.contracts import encode, digest, strict_json


def test_reconstruction_changes_and_clock_epoch():
    problem={'time':10,'machines':[{'machine':2},{'machine':1}],
             'operations':[{'operation_id':'z'},{'operation_id':'a'}]}
    base={'version':'base','tasks':[{'id':'t'}],'holds':[{'machine':1,'until':9}]}
    old=build_facts(problem,base)
    assert reconstruct(old)==(problem,base)
    problem['time']=11;problem['operations'].pop();problem['operations'].append({'operation_id':'new'})
    new=build_facts(problem,base)
    assert old['entities']['machines:2']['source_version']==new['entities']['machines:2']['source_version']
    assert old['entities']['machines:2']['entity_revision']!=new['entities']['machines:2']['entity_revision']
    delta=changes(old,new,page_size=1)
    assert apply_changes(old,delta)==new
    assert reconstruct(new)==(problem,base)
    bad=deepcopy(delta);bad['pages'].pop()
    with pytest.raises(HarnessError,match='change_gap'):apply_changes(old,bad)
    bad=deepcopy(old);bad['entities']['machines:2']['value']['machine']=3
    with pytest.raises(HarnessError,match='entity_version'):reconstruct(bad)


def test_reader_cache_and_missing_ids_detached():
    facts=build_facts({'machines':[],'operations':[{'operation_id':'z'},{'operation_id':'a'}]}, {'tasks':[],'holds':[]})
    reader=FactReader('context',facts)
    query={'kind':'operations','ids':['a','absent','z']}
    first=reader.read(query);assert first['status']=='partial'
    assert [r['id'] for r in first['entities']]==['a','z']
    first['entities'][0]['value']['operation_id']='tamper'
    assert reader.read(query)['entities'][0]['value']['operation_id']=='a'


def test_canonical_encoding_and_strict_json():
    assert encode({'b':2,'a':1})==b'{"a":1,"b":2}'
    assert digest({'b':2,'a':1})==digest({'a':1,'b':2})
    with pytest.raises(HarnessError,match='duplicate_json_key'):strict_json('{"a":1,"a":2}')
    with pytest.raises(HarnessError,match='nonfinite_json'):strict_json('NaN')
    with pytest.raises(ValueError):encode(float('nan'))
