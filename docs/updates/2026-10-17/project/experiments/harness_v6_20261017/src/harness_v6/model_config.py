"""Fail-closed binding of a frozen Codex model catalog and reasoning setting."""
import hashlib
from pathlib import Path
from .contracts import strict_json

FIELDS = {'model_catalog_json', 'model_catalog_sha256', 'reasoning_effort'}


def load(path):
    return None if path is None else strict_json(Path(path).read_bytes())


def admission_limit(value, *, model, context_token_budget):
    """Usable pre-request ceiling for the pinned Harness client.

    Its native auto-compaction threshold is at most floor(window * 0.9),
    even when a larger config override is supplied. Reject before that boundary.
    Callers count snapshot + complete overhead + output reserve against this.
    """
    settings(value, model=model, context_token_budget=context_token_budget)
    if value is None: return context_token_budget
    catalog = strict_json(Path(value['model_catalog_json']).read_bytes())
    row = next(row for row in catalog['models'] if row.get('slug') == model)
    percent = row.get('effective_context_window_percent', 95)
    if type(percent) is not int or not 0 < percent <= 100:
        raise ValueError('invalid effective model context percentage')
    # session.command sets auto_compact_token_limit=window+1. Native core then
    # clamps it to 90%; model catalog auto_compact defaults are overridden.
    return min(context_token_budget * percent // 100, context_token_budget * 9 // 10 - 1)


def settings(value, *, model, context_token_budget):
    if value is None:
        if model == 'gpt-6-astra':
            raise ValueError('gpt-6-astra requires a pinned model_config')
        return {}
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError('model_config requires exactly catalog path/hash and reasoning_effort')
    path = value['model_catalog_json']
    if not isinstance(path, str) or not Path(path).is_absolute():
        raise ValueError('model catalog path must be absolute')
    blob = Path(path).read_bytes()
    sha = value['model_catalog_sha256']
    if not isinstance(sha, str) or hashlib.sha256(blob).hexdigest() != sha:
        raise ValueError('model catalog SHA256 mismatch')
    catalog = strict_json(blob)
    models = catalog.get('models') if isinstance(catalog, dict) else None
    if not isinstance(models, list) or not all(isinstance(row, dict) for row in models):
        raise ValueError('invalid model catalog')
    matches = [row for row in models if row.get('slug') == model]
    if len(matches) != 1:
        raise ValueError('model must have exactly one catalog entry; fallback is forbidden')
    row = matches[0]
    levels = row.get('supported_reasoning_levels', [])
    effort = value['reasoning_effort']
    if not isinstance(effort, str) or not any(isinstance(r, dict) and r.get('effort') == effort for r in levels):
        raise ValueError('unsupported reasoning_effort')
    maximum = row.get('max_context_window') or row.get('context_window')
    if type(maximum) is not int or type(context_token_budget) is not int or not 0 < context_token_budget <= maximum:
        raise ValueError('context_token_budget exceeds catalog model window or is invalid')
    return {'model_catalog_json': path, 'model_reasoning_effort': effort}
