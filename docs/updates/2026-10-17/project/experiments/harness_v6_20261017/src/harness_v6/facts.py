"""Exact versioned facts. Source order is never a scheduling ranking.

v1 intentionally over-invalidates: the full observation is a dependency epoch.
This includes clock, all competitors and distant resource changes. Finer caches
may optimize this only after proving the same reconstruction/coverage contract.
"""
from copy import deepcopy

from .contracts import digest, require

IDENTITIES = {"machines": "machine", "operations": "operation_id", "tasks": "id", "holds": None}


def build_facts(problem, base):
    dependency_epoch = digest(problem)
    sources = {"machines": problem["machines"], "operations": problem["operations"],
               "tasks": base["tasks"], "holds": base["holds"]}
    entities = {}
    catalogs = {}
    for kind, rows in sources.items():
        catalog = []
        for i, row in enumerate(rows):
            identity = "h:" + str(i) if kind == "holds" else str(row[IDENTITIES[kind]])
            key = kind + ":" + identity
            require(key not in entities, "duplicate_fact", key)
            entity = {"kind": kind, "id": identity, "source_index": i, "value": deepcopy(row),
                      "source_version": digest(row), "dependency_epoch": dependency_epoch,
                      "dependencies": "complete_public_observation_including_clock_and_competing_resources"}
            entity["entity_revision"] = digest(entity)
            entities[key] = entity
            catalog.append(key)
        catalogs[kind] = catalog
    return {"schema": "harness-facts-v1", "problem_metadata": {k: deepcopy(v) for k, v in problem.items() if k not in ("machines", "operations")},
            "base_metadata": {k: deepcopy(v) for k, v in base.items() if k not in ("tasks", "holds")},
            "catalogs": catalogs, "entities": entities, "dependency_epoch": dependency_epoch,
            "problem_sha256": digest(problem), "base_sha256": digest(base)}


def reconstruct(facts):
    problem = deepcopy(facts["problem_metadata"])
    base = deepcopy(facts["base_metadata"])
    for kind, keys in facts["catalogs"].items():
        require(len(keys) == len(set(keys)), "catalog_duplicate", kind)
        rows = []
        for i, key in enumerate(keys):
            require(key in facts["entities"], "missing_entity", key)
            entity = facts["entities"][key]
            value = {k: v for k, v in entity.items() if k != "entity_revision"}
            require(entity["source_index"] == i and digest(value) == entity["entity_revision"]
                    and entity["source_version"] == digest(entity["value"])
                    and entity["dependency_epoch"] == facts["dependency_epoch"],
                    "entity_version", key)
            rows.append(deepcopy(entity["value"]))
        (problem if kind in ("machines", "operations") else base)[kind] = rows
    require(digest(problem) == facts["problem_sha256"] == facts["dependency_epoch"]
            and digest(base) == facts["base_sha256"], "reconstruction_mismatch", "Facts do not reconstruct original observation/base")
    return problem, base


def changes(previous, current, *, page_size=128):
    reconstruct(previous)
    reconstruct(current)
    updates = [{"key": key, "entity": deepcopy(entity)} for key, entity in current["entities"].items()
               if previous["entities"].get(key) != entity]
    updates += [{"key": key, "tombstone": True} for key in previous["entities"] if key not in current["entities"]]
    payload = {k: deepcopy(v) for k, v in current.items() if k != "entities"}
    pages = [updates[i:i + page_size] for i in range(0, len(updates), page_size)]
    return {"from_sha256": digest(previous), "to_sha256": digest(current), "metadata": payload,
            "pages": pages, "page_count": len(pages), "page_hashes": [digest(p) for p in pages],
            "update_count": len(updates), "dependency_coverage": current["dependency_epoch"]}


def apply_changes(previous, delta):
    require(delta["from_sha256"] == digest(previous), "change_gap", "Changes do not start at supplied version")
    require(len(delta["pages"]) == delta["page_count"] == len(delta["page_hashes"])
            and [digest(p) for p in delta["pages"]] == delta["page_hashes"], "change_gap", "Missing or damaged change page")
    entities = deepcopy(previous["entities"])
    count, seen = 0, set()
    for page in delta["pages"]:
        for change in page:
            key = change["key"]
            require(key not in seen, "change_duplicate", key)
            seen.add(key)
            count += 1
            if change.get("tombstone") is True:
                require(key in entities, "change_tombstone", key)
                del entities[key]
            else:
                entities[key] = deepcopy(change["entity"])
    result = {**deepcopy(delta["metadata"]), "entities": entities}
    require(count == delta["update_count"] and digest(result) == delta["to_sha256"]
            and result["dependency_epoch"] == delta["dependency_coverage"], "change_coverage", "Missing entity or dependency update")
    reconstruct(result)
    return result


class FactReader:
    def __init__(self, context_ref, facts):
        self.context_ref, self.facts = context_ref, facts
        self.cache = {}

    def cursor(self, kind, offset, where=None):
        identity = [self.context_ref, kind] if where is None else [self.context_ref, kind, where]
        return f"{digest(identity)[:24]}:{offset}"

    def read(self, query):
        require(type(query) is dict and set(query) <= {"kind", "ids", "cursor", "count", "fields", "where"}, "query_schema", "Unknown query fields")
        kind = query.get("kind")
        require(kind in IDENTITIES, "entity_kind", "Unknown entity type")
        catalog = self.facts["catalogs"][kind]
        catalog_total = len(catalog)
        require(("ids" in query) != ("cursor" in query), "query_schema", "Use exact IDs or a directory cursor")
        where = query.get("where")
        if "where" in query:
            require("ids" not in query and type(where) is list and 1 <= len(where) <= 16,
                    "query_filter", "A paginated filter needs 1..16 explicit predicates")
            known_fields = {field for key in catalog for field in self.facts["entities"][key]["value"]}
            for predicate in where:
                require(type(predicate) is dict and set(predicate) == {"field", "op", "value"} and
                        type(predicate["field"]) is str and predicate["field"] in known_fields and
                        predicate["op"] in ("eq", "contains") and
                        (predicate["value"] is None or type(predicate["value"]) in (str, int, float, bool)),
                        "query_filter", "Predicates use known public fields, eq/contains and a scalar value")
            def equal(left, right):
                return left == right and (type(left) is bool) == (type(right) is bool)
            def matches(value):
                for predicate in where:
                    field, requested = predicate["field"], predicate["value"]
                    if field not in value:
                        return False  # absence is not an explicit null
                    actual = value[field]
                    if predicate["op"] == "eq":
                        if not equal(actual, requested): return False
                    elif type(actual) is not list or not any(equal(v, requested) for v in actual):
                        return False
                return True
            # Pure model-specified predicate in original source order. No rank,
            # feasibility repair, objective, dispatch or candidate selection.
            catalog = [key for key in catalog if matches(self.facts["entities"][key]["value"])]
        missing = []
        if "ids" in query:
            ids = query["ids"]
            require(type(ids) is list and all(type(i) in (str, int) for i in ids), "entity_ids", "Exact IDs required")
            require(len(ids) <= 512, "entity_ids_limit", "At most 512 IDs per query; no IDs were read")
            keys = [kind + ":" + str(i) for i in ids]
            require(len(keys) == len(set(keys)), "entity_missing", "Duplicate requested entity ID")
            missing = [{"kind": kind, "id": str(i), "code": "entity_missing",
                        "context_ref": self.context_ref, "meaning": "absent_from_current_catalog_only"}
                       for i, key in zip(ids, keys) if key not in self.facts["entities"]]
            keys = [key for key in keys if key in self.facts["entities"]]
            next_cursor = None
        else:
            cursor, count = query["cursor"], query.get("count")
            if where is not None and cursor is None:
                cursor = self.cursor(kind, 0, where)
            require(type(cursor) is str and cursor.startswith(self.cursor(kind, 0, where).rsplit(":", 1)[0] + ":"), "stale_cursor", "Cursor belongs to another context/kind/filter")
            suffix = cursor.rsplit(":", 1)[1]
            require(suffix.isdigit() and type(count) is int and 1 <= count <= 512, "page_size", "Count must be 1..512")
            offset = int(suffix)
            require(0 <= offset <= len(catalog), "page_offset", "Offset outside directory")
            keys = catalog[offset:offset + count]
            next_cursor = self.cursor(kind, offset + len(keys), where) if offset + len(keys) < len(catalog) else None
        fields = query.get("fields")
        require(fields is None or (type(fields) is list and all(type(f) is str for f in fields) and len(fields) == len(set(fields))), "projection", "Explicit unique fields required")
        rows = []
        for key in keys:
            entity = self.facts["entities"][key]
            cache_key = (kind, entity["id"], entity["entity_revision"], entity["source_version"], digest(fields))
            if cache_key not in self.cache:
                row = deepcopy(entity)
                if fields is not None:
                    row["value"] = {k: deepcopy(entity["value"][k]) for k in fields if k in entity["value"]}
                row["projection_fields"] = fields
                row["absent_fields"] = [] if fields is None else [k for k in fields if k not in entity["value"]]
                row["original_ref"] = {"context_ref": self.context_ref, "kind": kind, "id": entity["id"]}
                self.cache[cache_key] = row
            rows.append(deepcopy(self.cache[cache_key]))
        result = {"status": "ok", "context_ref": self.context_ref, "entities": rows,
                  "catalog_total": catalog_total, "returned": len(rows), "next_cursor": next_cursor,
                  "order": "requested_ID_order_or_fixed_source_order", "complete_requested_slice": True}
        if missing:
            result.update(status="partial", complete_requested_slice=False,
                          requested_count=len(query["ids"]), missing_entities=missing,
                          missing_meaning="No entity or completion state inferred; valid requested IDs are returned unchanged")
        if where is not None:
            result.update(where=deepcopy(where), matching_total=len(catalog), filtering="exact_model_predicates_only_no_ranking")
        return result
