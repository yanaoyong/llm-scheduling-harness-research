"""Lossless retention of requested public facts within one state context."""
from copy import deepcopy

from .contracts import digest, encode, require
from .presentation import pack, unpack

INSTRUCTIONS = """
same_context_fact_memory retains public facts already requested in this exact context.
Use its known values and query outcomes directly; changing fields/count or query batch does
not make already-known facts new. Request additional facts only for a remaining information
gap. It does not recommend tasks, machines, batches, ordering, timing, holds or a candidate.
Decode each value table using its encoding field; shared-value cells are dictionary indices,
not inferred values. Unrequested fields remain unknown; confirmed_absent_fields are distinct
from explicit null. Exact provenance and original responses remain at full_memory_ref.
If values or the catalog are explicitly marked non-inline, read the indicated artifact path
to reuse the saved facts. A later context has a separate memory; never transfer stale facts.
"""


class FactMemory:
    def __init__(self, context_ref):
        self.context_ref = context_ref
        self.facts = []
        self.reads = []
        self._indices = {}
        self._absent = {}

    def add(self, call, action, response, result_ref=None):
        require(action.get('tool') == 'read_entities' and
                action.get('context_ref') == response.get('context_ref') == self.context_ref and
                response.get('status') == 'ok', 'fact_memory', 'Successful current-context read required')
        skeleton = deepcopy(response)
        for result in skeleton.get('results', []):
            descriptors = []
            for entity in result.get('entities', []):
                require(type(entity) is dict and type(entity.get('value')) is dict,
                        'fact_memory', 'Exact public entity record required')
                origin = entity.get('original_ref', {})
                require(origin.get('context_ref') == self.context_ref and
                        origin.get('kind') == entity.get('kind') and origin.get('id') == entity.get('id'),
                        'fact_memory_context', 'Entity source must belong to the exact requested context')
                base = {k: deepcopy(v) for k, v in entity.items()
                        if k not in ('value', 'projection_fields', 'absent_fields')}
                key = digest(base)
                if key not in self._indices:
                    self._indices[key] = len(self.facts)
                    self.facts.append({'identity': base, 'value': {}})
                index = self._indices[key]
                stored = self.facts[index]['value']
                absent = self._absent.setdefault(index, set())
                new_absent = entity.get('absent_fields', [])
                require(type(new_absent) is list and all(type(field) is str for field in new_absent),
                        'fact_memory', 'Explicit absent-field names required')
                require(not (set(new_absent) & (set(stored) | set(entity['value']))) and
                        not (absent & set(entity['value'])),
                        'fact_memory_conflict', 'Absent and known fields cannot conflict')
                absent.update(new_absent)
                for field, value in entity['value'].items():
                    require(field not in stored or digest(stored[field]) == digest(value),
                            'fact_memory_conflict', 'Same immutable entity field changed')
                    stored[field] = deepcopy(value)
                descriptors.append({
                    'fact_index': index, 'value_fields': list(entity['value']),
                    'metadata': {k: deepcopy(entity[k]) for k in ('projection_fields', 'absent_fields')
                                 if k in entity},
                })
            if 'entities' in result:
                result['entities'] = descriptors
        self.reads.append({'call': call, 'action': deepcopy(action),
                           'result_ref': result_ref, 'result': skeleton})
        return len(self.reads) - 1

    def restore(self, index):
        result = deepcopy(self.reads[index]['result'])
        for query_result in result.get('results', []):
            if 'entities' not in query_result:
                continue
            restored = []
            for descriptor in query_result['entities']:
                fact = self.facts[descriptor['fact_index']]
                entity = deepcopy(fact['identity'])
                entity.update(deepcopy(descriptor['metadata']))
                entity['value'] = {k: deepcopy(fact['value'][k]) for k in descriptor['value_fields']}
                restored.append(entity)
            query_result['entities'] = restored
        return result

    def public(self):
        return {'schema': 'same-context-requested-fact-memory-v1',
                'context_ref': self.context_ref, 'entity_order': 'first_requested_occurrence',
                'facts': deepcopy(self.facts), 'reads': deepcopy(self.reads),
                'interpretation': 'Exact public facts requested in this context only. '
                                  'Fact values combine consistent projections of the same immutable entity. '
                                  'Each read retains its original query, totals, cursor, source identity and '
                                  'field-selection descriptor so its exact response is reconstructable. '
                                  'No ranking, production choice or missing value is inferred.'}

    def inline(self, full_memory_ref):
        """All known values inline; exact response/provenance metadata stays addressable."""
        buckets = {}
        for index, fact in enumerate(self.facts):
            key = (fact['identity']['kind'], tuple(fact['value']))
            buckets.setdefault(key, []).append((index, fact))
        pool, pool_indices, groups = [], {}, []
        for (kind, fields), items in buckets.items():
            constants = {field: deepcopy(items[0][1]['value'][field]) for field in fields
                         if all(digest(fact['value'][field]) == digest(items[0][1]['value'][field])
                                for _, fact in items)}
            variable = [field for field in fields if field not in constants]
            shared = []
            for field in variable:
                values = [fact['value'][field] for _, fact in items]
                fresh = {digest(value): value for value in values if digest(value) not in pool_indices}
                literal_size = sum(len(encode(value)) for value in values)
                shared_size = sum(len(encode(value)) + 1 for value in fresh.values()) + len(values) * 5 + 20
                if shared_size < literal_size:
                    shared.append(field)
                    for key, value in fresh.items():
                        pool_indices[key] = len(pool)
                        pool.append(deepcopy(value))
            rows = [[index, fact['identity']['id'],
                     *[pool_indices[digest(fact['value'][field])] if field in shared
                       else deepcopy(fact['value'][field]) for field in variable]]
                    for index, fact in items]
            groups.append({'kind': kind, 'value_fields': list(fields), 'constants': constants,
                           'variable_fields': variable, 'shared_fields': shared, 'rows': rows})
        queries, absent = [], {}
        for read_index, read in enumerate(self.reads):
            request_queries = read['action'].get('queries')
            for query_index, result in enumerate(read['result'].get('results', [])):
                descriptors = result.get('entities', [])
                for descriptor in descriptors:
                    fields = descriptor['metadata'].get('absent_fields', [])
                    if fields:
                        absent.setdefault(descriptor['fact_index'], set()).update(fields)
                queries.append({
                    'call': read['call'], 'read_index': read_index, 'query_index': query_index,
                    'request': deepcopy(request_queries[query_index] if request_queries is not None
                                        else read['action']),
                    'result_metadata': {key: deepcopy(value) for key, value in result.items() if key != 'entities'},
                    'fact_indices': [descriptor['fact_index'] for descriptor in descriptors],
                })
        common_metadata = {}
        if queries:
            common_keys = set.intersection(*(set(query['result_metadata']) for query in queries))
            common_metadata = {key: deepcopy(queries[0]['result_metadata'][key]) for key in sorted(common_keys)
                               if all(digest(query['result_metadata'][key]) ==
                                      digest(queries[0]['result_metadata'][key]) for query in queries)}
        index_sets, index_counts = {}, {}
        for query in queries:
            query['result_metadata'] = {key: value for key, value in query['result_metadata'].items()
                                        if key not in common_metadata}
            if ('where' in query['result_metadata'] and
                    query['result_metadata']['where'] == query['request'].get('where')):
                query['result_metadata'].pop('where')
                query['result_where_equals_request_where'] = True
            key = digest(query['fact_indices'])
            index_counts[key] = index_counts.get(key, 0) + 1
        for query in queries:
            key = digest(query['fact_indices'])
            if len(query['fact_indices']) >= 8 and index_counts[key] > 1:
                if key not in index_sets:
                    index_sets[key] = (len(index_sets), query['fact_indices'])
                query['fact_index_set'] = index_sets[key][0]
                query.pop('fact_indices')
        return {
            'schema': 'same-context-fact-value-tables-v1', 'context_ref': self.context_ref,
            'full_memory_ref': full_memory_ref, 'fact_count': len(self.facts),
            'all_known_field_values_inline': True, 'groups': groups, 'shared_values': pool,
            'queries': pack(queries), 'common_result_metadata': common_metadata,
            'fact_index_sets': [value for _, value in index_sets.values()],
            'confirmed_absent_fields': [{'fact_index': index, 'fields': sorted(fields)}
                                        for index, fields in sorted(absent.items())],
            'encoding': 'Each row is [fact_index, id, ...variable_fields]. kind and constants apply to every '
                        'row in that group. A cell in shared_fields is an integer index into shared_values; '
                        'all other cells and all constants are literal JSON values. Missing unrequested '
                        'fields remain unknown. Restore source order by fact_index. Exact entity provenance '
                        'is at full_memory_ref path [facts, fact_index, identity]; exact response reconstruction '
                        'metadata is at [reads, read_index, result]. Decode queries using the existing lossless '
                        'record-table format. Merge common_result_metadata into each result_metadata. '
                        'result_where_equals_request_where means the original result where equals request.where. '
                        'fact_indices preserve returned order; fact_index_set instead indexes fact_index_sets. '
                        'This cache contains previously requested facts, not a production recommendation.',
        }


def restore_inline_values(view):
    pool, restored = view['shared_values'], {}
    for group in view['groups']:
        for row in group['rows']:
            index, entity_id = row[:2]
            require(index not in restored and len(row) == 2 + len(group['variable_fields']),
                    'fact_memory', 'Unique fact index and exact row width required')
            values = deepcopy(group['constants'])
            values.update({field: deepcopy(pool[value] if field in group['shared_fields'] else value)
                           for field, value in zip(group['variable_fields'], row[2:])})
            require(set(values) == set(group['value_fields']), 'fact_memory', 'All known fields required')
            restored[index] = {'kind': group['kind'], 'id': entity_id, 'value': values}
    require(len(restored) == view['fact_count'], 'fact_memory', 'Every fact required')
    return restored


def prompt_variants(runtime, attempts, frame, base_chars):
    """Offer lossless full values, explicit catalog fallback, then a public reference.

    Only successful reads of this current context are eligible. Nothing is
    synthesized from private state, prior contexts, notes or unrequested data.
    The caller chooses solely by serialized prompt capacity, never production merit.
    """
    from .contracts import strict_json
    context_ref = frame['context']['context_ref']
    memory, indices, responses = FactMemory(context_ref), {}, {}
    for attempt_id, attempt in sorted(attempts, key=lambda item: item[1]['index']):
        if (attempt.get('context_ref') != context_ref or attempt.get('status') != 'processed'
                or not attempt.get('response_ref')):
            continue
        try:
            raw = strict_json(runtime.store.bytes(attempt['raw_ref']))
        except (ValueError, UnicodeDecodeError):
            continue
        action = raw.get('action', raw) if type(raw) is dict else None
        if type(action) is not dict or action.get('tool') != 'read_entities':
            continue
        response = runtime.store.get(attempt['response_ref'])
        if response.get('status') != 'ok':
            continue
        entry = runtime.store.read('interaction_entries', attempt_id, {})
        indices[attempt_id] = memory.add(attempt['index'] + 1, action, response, entry.get('result_ref'))
        responses[attempt_id] = response
    if len(memory.reads) < 2:
        return []
    visible = {}
    for entry in frame['interaction_history']['entries']:
        if 'result' in entry:
            visible[entry['attempt_id']] = unpack(entry['result'])
    latest_id = attempts[-1][0] if attempts else None
    if latest_id in indices and frame.get('last_tool_feedback') is not None:
        visible[latest_id] = unpack(frame['last_tool_feedback'])
    if (base_chars <= runtime.config['limits']['context_chars'] and
            all(attempt_id in visible and digest(visible[attempt_id]) == digest(response)
                for attempt_id, response in responses.items())):
        return []

    full = memory.public()
    full_hash = digest(full)
    public_kind = 'same_context_requested_facts'
    reference = next((ref for ref, record in runtime.store.rows('public')
                      if record.get('kind') == public_kind and record.get('object_ref') == full_hash
                      and record.get('run_id') == runtime.manifest['run_id']), None)
    if reference is None:
        with runtime.store.transaction():
            reference = runtime._publish(full, public_kind)
    candidate = deepcopy(frame)
    candidate['same_context_fact_memory'] = memory.inline(reference)
    for entry in candidate['interaction_history']['entries']:
        if entry['attempt_id'] in indices:
            entry.pop('result', None)
            entry.pop('result_preview', None)
            entry['result_inline_at'] = 'same_context_fact_memory'
            entry['fact_memory_read_index'] = indices[entry['attempt_id']]
    if latest_id in indices:
        candidate['last_tool_feedback'] = {key: deepcopy(value) for key, value in responses[latest_id].items()
                                           if key != 'results'}
        candidate['last_tool_feedback'].update(results_inline_at='same_context_fact_memory',
                                                fact_memory_read_index=indices[latest_id])
    catalog = deepcopy(candidate)
    facts = catalog['same_context_fact_memory']
    groups = facts.pop('groups')
    facts.pop('shared_values')
    facts.update(all_known_field_values_inline=False, values_locator={'artifact_ref': reference, 'path': ['facts']},
                 catalog_inline=True,
                 catalog=[{'kind':group['kind'], 'known_fields':group['value_fields'],
                           'rows':[row[:2] for row in group['rows']]} for group in groups],
                 encoding='Values are explicitly out of line. Catalog rows identify every retained entity and '
                          'known field. Each group supplies kind and known_fields for rows [fact_index, id]. '
                          'Read full_memory_ref path [facts, fact_index, value] for exact values; '
                          '[facts, fact_index, identity] for exact provenance. Query order and metadata are '
                          'encoded with the lossless record-table format. Merge common_result_metadata into each '
                          'result_metadata; result_where_equals_request_where restores request.where. '
                          'fact_indices preserve returned order; fact_index_set indexes fact_index_sets. '
                          'No omitted value is null or absent.')
    reference_only = deepcopy(candidate)
    reference_only['same_context_fact_memory'] = {
        'schema': 'same-context-fact-memory-reference-v1', 'context_ref': context_ref,
        'full_memory_ref': reference, 'fact_count': len(memory.facts), 'read_count': len(memory.reads),
        'all_known_field_values_inline': False, 'catalog_inline': False, 'queries_inline': False,
        'facts_locator': {'artifact_ref': reference, 'path': ['facts']},
        'reads_locator': {'artifact_ref': reference, 'path': ['reads']},
        'interpretation': 'Capacity fallback: exact known values, identity metadata, query results and ordering '
                          'are all retained in the current-context public artifact. Read it to reuse facts; '
                          'no values have been filled, ranked, silently discarded or transferred from another context.',
    }
    return [candidate, catalog, reference_only]
