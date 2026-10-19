"""Fail-closed interpretation of Codex's model-facing tool declarations."""
from .mcp_server import TOOLS


def request_tools(body):
    """Read ordinary Responses or one complete Responses Lite declaration.

    Lite relocates tool schemas to a developer additional_tools input item.
    Mixed or repeated declaration sources are rejected, not merged silently.
    """
    inputs = body.get('input', [])
    blocks = [item for item in inputs if isinstance(item, dict) and item.get('type') == 'additional_tools'] if isinstance(inputs, list) else []
    if blocks:
        if len(blocks) != 1 or 'tools' in body:
            raise ValueError('ambiguous or repeated tool declaration source')
        block = blocks[0]
        if block.get('role') != 'developer' or set(block) - {'type', 'role', 'tools', 'id'}:
            raise ValueError('invalid additional_tools declaration')
        tools = block.get('tools')
    else:
        tools = body.get('tools', [])
    declared_tools(tools)
    return tools


def declared_tools(tools):
    if not isinstance(tools, list):
        raise ValueError('tools must be an array')
    result = {}
    def add(tool, namespace=None):
        if not isinstance(tool, dict) or tool.get('type') != 'function':
            raise ValueError('only explicit function schemas supported')
        if not isinstance(tool.get('parameters'), dict):
            raise ValueError('function parameters must be an object')
        name = tool.get('name')
        if not isinstance(name, str):
            raise ValueError('function name must be a string')
        short = name.removeprefix('mcp__harness_v6__') if namespace is None else name
        if short not in TOOLS or short in result:
            raise ValueError('unexpected native/foreign/duplicate tool: '+name)
        if tool.get('defer_loading'):
            raise ValueError('deferred tool declarations are not permitted')
        result[short] = (namespace, name)
    for tool in tools:
        if isinstance(tool, dict) and tool.get('type') == 'namespace':
            if tool.get('name') != 'mcp__harness_v6' or not isinstance(tool.get('tools'), list):
                raise ValueError('unexpected tool namespace')
            if tool.get('defer_loading'):
                raise ValueError('deferred namespaces are not permitted')
            for child in tool['tools']:
                add(child, tool['name'])
        else:
            add(tool)
    return result
