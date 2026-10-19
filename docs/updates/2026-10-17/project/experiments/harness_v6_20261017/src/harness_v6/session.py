"""Session policy and host-only adoption. Runner injection never launches an LLM here."""
from dataclasses import dataclass
import json
import sys
from typing import Protocol
from .contracts import strict_json
from .evidence import audit_provenance
from .mcp_server import TOOLS

# Provisional wire names: ALL require M5(b) validation against pinned Mac binary.
EVENT_TYPES={'passive_items':frozenset({'agent_message','reasoning'}),
             'mcp_item':'mcp_tool_call',
             'passive_events':frozenset({'thread.started','turn.started'}),
             'item_events':frozenset({'item.started','item.updated','item.completed'}),
             'compaction':frozenset({'thread.compacted','context.compacted','compaction'})}

@dataclass(frozen=True)
class Budget:
    max_tool_calls:int=100
    wall_seconds:float=300
    token_cap:int=100000
    def __post_init__(self):
        if self.max_tool_calls<1 or self.wall_seconds<=0 or self.token_cap<1: raise ValueError('invalid budget')

@dataclass
class RunResult:
    jsonl:str
    returncode:int=0
    wall_seconds:float=0
    timed_out:bool=False
    model_seconds:float=0

class Runner(Protocol):
    def run(self, command:list, prompt:str, *, timeout:float)->RunResult: ...

def command(input_dir, output_dir, *, model, budget=Budget(), binary='codex', python=sys.executable, env=None,
            context_token_budget=None, output_reserve_tokens=None, model_config=None):
    args=['-m','harness_v6.mcp_server','--input',str(input_dir),'--output',str(output_dir),'--max-tool-calls',str(budget.max_tool_calls)]
    settings={'approval_policy':'never','history.persistence':'none','shell_environment_policy.inherit':'none',
              'include_environment_context':False,'include_apps_instructions':False,
              'include_collaboration_mode_instructions':False,'skills.include_instructions':False,
              'skills.bundled.enabled':False,
              'features.shell_snapshot':False,'features.shell_tool':False,'web_search':'disabled','features.view_image':False,
              'features.multi_agent':False,'tools.update_plan.enabled':False,
              'features.async_compaction':False,'model_post_turn_compact_threshold_percent':0,
              'tools.experimental_request_user_input.enabled':False,
              'tool_output_token_limit':context_token_budget or budget.token_cap,
              'features.goals':False,'features.code_mode':False,
              'features.code_mode_only':False,'features.code_mode_host':False,
              'features.rollout_budget':False,
              'features.sleep_tool':False,
              'features.unified_exec':False,
              'features.hooks':False,
              'features.apps':False,
              'features.tool_suggest':False,
              'features.plugins':False,
              'features.browser_use':False,
              'features.computer_use':False,
              'features.image_generation':False,
              'features.skill_search':False,
              'features.skill_mcp_dependency_install':False,
              'features.workspace_dependencies':False,
              'features.current_time_reminder':False,
              'model_context_window':context_token_budget or budget.token_cap,
              'model_auto_compact_token_limit':(context_token_budget or budget.token_cap)+1,
              'mcp_servers.harness_v6.command':python,'mcp_servers.harness_v6.args':args,
              'mcp_servers.harness_v6.required':True,
              'mcp_servers.harness_v6.startup_timeout_sec':min(30,budget.wall_seconds),
              'mcp_servers.harness_v6.tool_timeout_sec':budget.wall_seconds}
    from .model_config import settings as model_settings
    settings.update(model_settings(model_config, model=model,
        context_token_budget=context_token_budget or budget.token_cap))
    # Explicit consent is scoped to the three local Harness tools only.
    settings['mcp_servers.harness_v6.enabled_tools'] = list(TOOLS)
    settings.update({'mcp_servers.harness_v6.tools.'+name+'.approval_mode':'approve' for name in TOOLS})
    # TOML inline table, not JSON object syntax.
    settings.update({'mcp_servers.harness_v6.env.'+k:v for k,v in (env or {}).items()})
    argv=[binary,'exec','--ephemeral','--json','--ignore-user-config','--ignore-rules','--skip-git-repo-check','--sandbox','read-only','--model',model,'--cd',str(input_dir)]
    for key,value in settings.items(): argv+=['-c',key+'='+json.dumps(value)]
    return argv+['-']

def classify(jsonl, *, interaction="mcp_session"):
    if interaction not in ("single_action", "mcp_session"):
        raise ValueError("unknown interaction")
    calls=[];errors=[];usage=None;completed=False;ids=set();pending=set();rounds=0;in_round=False
    for line in jsonl.splitlines():
        try:
            e=strict_json(line);kind=e['type']
            if completed: errors.append('event_after_completion')
            if kind in EVENT_TYPES['compaction']: errors.append('compaction')
            elif kind in EVENT_TYPES['passive_events']: pass
            elif kind in EVENT_TYPES['item_events']:
                item=e['item'];typ=item['type']
                if (kind=='item.completed' and typ=='error' and isinstance(item.get('message'),str)
                        and item['message'].startswith('Heads up: Long threads and multiple compactions')):
                    errors.append('compaction')
                elif typ in EVENT_TYPES['passive_items']: pass
                elif interaction == 'single_action': errors.append('forbidden_item:'+str(typ))
                elif typ==EVENT_TYPES['mcp_item']:
                    if kind=='item.started':
                        rounds += not in_round
                        in_round=True
                    elif kind=='item.completed': in_round=False
                    if item.get('server')!='harness_v6': errors.append('foreign_mcp')
                    if item.get('tool') not in TOOLS: errors.append('unknown_tool')
                    if kind in ('item.started','item.updated'): pending.add(item['id'])
                    if kind=='item.completed':
                        pending.discard(item['id'])
                        if item.get('status')!='completed': errors.append('mcp_failed')
                        if item['id'] in ids: errors.append('duplicate_item')
                        ids.add(item['id'])
                        args=item['arguments']
                        if isinstance(args,str): args=strict_json(args)
                        if not isinstance(args,dict): raise ValueError('arguments')
                        calls.append({'tool':item['tool'],'arguments':args})
                else: errors.append('forbidden_item:'+str(typ))
            elif kind=='turn.completed':
                if completed: errors.append('multiple_turns')
                completed=True
                u=e.get('usage',{})
                if all(type(u.get(k)) is int and u[k]>=0 for k in ('input_tokens','cached_input_tokens','output_tokens')) and u['cached_input_tokens']<=u['input_tokens']: usage=u
                else: errors.append('usage_unknown')
            elif kind in ('error', 'turn.failed'):
                message=e.get('message') if kind=='error' else e.get('error',{}).get('message')
                if isinstance(message,str) and 'HARNESS_FORBIDDEN_TOOL:' in message:
                    errors.append('forbidden_item:unadvertised_tool')
                errors.append('failed_event:'+kind)
            else: errors.append('unknown_event:'+str(kind))
        except (ValueError,KeyError,TypeError,AttributeError): errors.append('malformed_jsonl')
    if pending: errors.append('incomplete_mcp_items')
    if not completed: errors.append('missing_turn_completed')
    if usage is None: errors.append('usage_unknown')
    return {'calls':calls,'errors':errors,'usage':usage,'tool_rounds':rounds,'tool_calls':len(ids|pending)}

def finish(result, *, rows, submission, initial_state, commit, metrics, now, budget=Budget(), cycle=None, model_note=''):
    parsed=classify(result.jsonl);errors=list(parsed['errors']);u=parsed['usage']
    if result.returncode or result.timed_out: errors.append('process_failed')
    if result.wall_seconds>budget.wall_seconds: errors.append('wall_budget')
    if len(rows)>budget.max_tool_calls: errors.append('tool_budget')
    if u and u['input_tokens']+u['output_tokens']>budget.token_cap: errors.append('token_budget')
    try:
        errors.extend(audit_provenance(rows,parsed['calls'],submission,initial_state))
    except (KeyError,TypeError,ValueError,AttributeError):
        errors.append('malformed_evidence')
    adopted=False
    if not errors:
        try:
            # Callable must implement atomic compare-and-commit, not check-then-write.
            adopted=bool(commit(initial_state['state_version'],submission['plan']))
            if not adopted: errors.append('stale_state_version')
        except Exception as exc: errors.append('commit_failed:'+str(exc))
    usage=u or {};known=u is not None
    metrics.session(now,tool_calls=len(rows),tool_rounds=parsed['tool_rounds'],input_tokens=usage.get('input_tokens',0),cached_tokens=usage.get('cached_input_tokens',0),output_tokens=usage.get('output_tokens',0),model_seconds=result.model_seconds,wall_seconds=result.wall_seconds,failed=not adopted,usage_known=known,submit_attempts=sum(r['tool']=='submit_plan' for r in rows),submit_rejections=sum(r['tool']=='submit_plan' and not r['result'].get('accepted') for r in rows))
    if cycle is not None: cycle.finish(submitted=adopted,process_ok=not errors,usage_known=known,cost=usage.get('input_tokens',0)-usage.get('cached_input_tokens',0)*(1-metrics.cached_input_weight),wall_seconds=result.wall_seconds,model_note=model_note)
    return {'adopted':adopted,'errors':errors,'usage_unknown':not known}

def run_session(runner, argv, prompt, *, budget=Budget(), checkpoint=None,
                inflight_bundle=None, persist_completed=None, **finish_args):
    if checkpoint is not None:
        if inflight_bundle is None or persist_completed is None:
            raise ValueError('durable session requires in-flight bundle and completed checkpoint callback')
        checkpoint.mark_inflight(inflight_bundle)
    try:
        result=runner.run(argv,prompt,timeout=budget.wall_seconds)
    except (TimeoutError, OSError):
        result=RunResult('',returncode=1,wall_seconds=budget.wall_seconds,timed_out=True)
    # Artifact reading is host-owned and occurs after the runner exits.
    try:
        artifacts=finish_args.pop('artifacts')()
    except (OSError, ValueError):
        artifacts={'rows':[], 'submission':None}
    outcome=finish(result,budget=budget,**finish_args,**artifacts)
    if checkpoint is not None:
        persist_completed(outcome)
        checkpoint.clear_inflight()
    return outcome


def read_artifacts(output_dir):
    from pathlib import Path
    directory=Path(output_dir)
    log=directory/'mcp.jsonl'
    rows=[strict_json(line) for line in log.read_bytes().splitlines()] if log.exists() else []
    path=directory/'submission.json'
    return {'rows':rows,'submission':strict_json(path.read_bytes()) if path.exists() else None}
