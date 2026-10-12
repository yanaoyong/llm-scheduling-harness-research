"""A tiny real inference plus tool-capability inventory; never schedules jobs."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from model_transport import ModelConfig, call_model

PROBE_PROMPT = 'Compute 17+26. Audit only the ACTUAL tool descriptions in your context. List all native tools. For functions.exec list EVERY described host tools.* method, including ALL_TOOLS entries if exposed; do not invoke any tools. Report the total concurrent-agent slot limit in your developer context. List every available file-read, shell-execution, network, web, MCP capability; empty if none. Use no tools. Return JSON.'
PROBE_SCHEMA = {
    'type': 'object', 'properties': {
        'sum': {'type': 'integer'},
        'native_tool_names': {'type': 'array', 'items': {'type': 'string'}},
        'functions_exec_host_tool_names': {'type': 'array', 'items': {'type': 'string'}},
        'agent_concurrency_limit': {'type': 'integer'},
        'file_network_shell_capabilities': {'type': 'array', 'items': {'type': 'string'}},
    },
    'required': ['sum', 'native_tool_names', 'functions_exec_host_tool_names', 'agent_concurrency_limit', 'file_network_shell_capabilities'],
    'additionalProperties': False,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', type=Path, default=ROOT / 'runs/development/channel_probe_recheck')
    parser.add_argument('--model', default='gpt-6-astra')
    parser.add_argument('--effort', default='medium')
    parser.add_argument('--codex-binary', default=ModelConfig().codex_binary)
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    result = call_model(PROBE_PROMPT, PROBE_SCHEMA, args.run_dir,
                        ModelConfig(model=args.model, reasoning_effort=args.effort, timeout_seconds=args.timeout,
                                    codex_binary=args.codex_binary), resume=args.resume)
    print(json.dumps({key: result[key] for key in ('status', 'failure_reason', 'output', 'duration_seconds', 'usage', 'native_tool_events', 'model_calls', 'cost_usd')}, indent=2))
    output = result.get('output') or {}
    safe_control_names = {
        'functions.wait', 'functions.request_user_input', 'functions.request_user_input_async',
        'functions.exec', 'collaboration.followup_task', 'collaboration.interrupt_agent',
        'collaboration.list_agents', 'collaboration.send_message', 'collaboration.spawn_agent',
    }
    # Inventory is model self-report, corroborated by config and zero native event audit.
    # apply_patch is ineffective under the read-only sandbox and disabled code-mode host.
    valid = (result['status'] == 'success' and output.get('sum') == 43
             and output.get('agent_concurrency_limit') == 1
             and output.get('file_network_shell_capabilities') == []
             and set(output.get('functions_exec_host_tool_names', [])) <= {'tools.apply_patch', 'tools.clock__curr_time'}
             and set(output.get('native_tool_names', [])) <= safe_control_names)
    if not valid:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
