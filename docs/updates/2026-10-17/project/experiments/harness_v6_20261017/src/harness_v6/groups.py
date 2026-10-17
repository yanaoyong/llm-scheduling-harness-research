"""Registered 2×2 factors; all groups share ledger, snapshot and submit logic."""
from dataclasses import replace
from .cycle import CycleConfig

GROUPS = {
    'E1': {'trigger': 'event', 'interaction': 'single_action'},
    'P1': {'trigger': 'periodic', 'interaction': 'single_action'},
    'E2': {'trigger': 'event', 'interaction': 'mcp_session'},
    'P2': {'trigger': 'periodic', 'interaction': 'mcp_session'},
}


def config_for(group, config=None):
    if group not in GROUPS:
        raise ValueError('unknown experiment group')
    return replace(config or CycleConfig(), **GROUPS[group])


def validate_mapping(group, config):
    expected = GROUPS.get(group)
    return expected is not None and isinstance(config, dict) and all(config.get(k) == v for k, v in expected.items())
