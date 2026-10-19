import pytest
from harness_v6.tool_contract import declared_tools, request_tools


def tool(name='read_entities'):
    return dict(type='function', name=name, parameters={'type':'object'})


def test_exact_names_and_namespace():
    assert declared_tools([tool('mcp__harness_v6__read_entities')]) == {
        'read_entities': (None, 'mcp__harness_v6__read_entities')}
    assert declared_tools([dict(type='namespace', name='mcp__harness_v6', tools=[tool()])]) == {
        'read_entities': ('mcp__harness_v6', 'read_entities')}
    assert declared_tools([]) == {}


@pytest.mark.parametrize('tools', [
    [tool('foreign_read_entities')], [tool('apply_patch')], [tool(),tool()],
    [dict(type='tool_search')], [dict(type='custom',name='apply_patch')],
    [dict(type='namespace',name='functions',tools=[tool()])],
    [dict(tool(),defer_loading=True)],
    [dict(type='namespace',name='mcp__harness_v6',tools=[tool()],defer_loading=True)],
])
def test_extra_tools_never_pass(tools):
    with pytest.raises(ValueError): declared_tools(tools)


def test_responses_lite_schema_is_equally_strict():
    allowed = [dict(type='namespace', name='mcp__harness_v6', tools=[tool()])]
    block = dict(type='additional_tools', role='developer', tools=allowed)
    assert request_tools({'input': [block]}) == allowed
    assert request_tools({'input': [dict(block, tools=[])]}) == []
    for body in ({'tools': [], 'input': [block]}, {'input': [block, block]},
                 {'input': [dict(block, role='user')]}, {'input': [dict(block, unknown=True)]},
                 {'input': [dict(block, tools=[tool('apply_patch')])]}, {'input': [dict(block, tools=None)]}):
        with pytest.raises(ValueError): request_tools(body)
