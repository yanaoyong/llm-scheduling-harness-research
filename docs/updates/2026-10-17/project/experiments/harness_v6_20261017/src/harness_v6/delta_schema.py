"""Single model-facing decision schema shared by both transports."""
from copy import deepcopy


def obj(properties, required=None, description=''):
    return dict(type='object', properties=properties, required=list(properties) if required is None else required,
                additionalProperties=False, description=description)


def array(items):
    return dict(type='array', items=items)


ID = dict(type='string', minLength=1)
IDS = dict(type='array', items=ID, uniqueItems=True)
TASK = obj(dict(id=ID, operation_ids=dict(IDS, minItems=1),
                start_mode=dict(type='string', enum=['when_ready', 'not_before'], description='Defaults to when_ready.'),
                not_before=dict(type='number', description='Optional hard lower bound; past values are satisfied.'),
                latest_start=dict(type='number', description='Latest allowed start; expiry invalidates the task.')),
           ['id', 'operation_ids'], 'Machine and queue position come only from machine_orders; identity comes from observation.')
HOLD = obj(dict(machine=dict(type='integer'), until=dict(type='number'), reason=ID,
                after_task_id=dict(type=['string', 'null'], description='Conditional: applies after this task executes and queue is empty. Omit/null for unconditional.')),
           ['machine', 'until', 'reason'])

def patch(item, replacement):
    return obj(dict(cancel_ids=IDS, replace=array(replacement), add=array(item)),
               description='Unmentioned base items are retained. Cancellation and replacement IDs must be disjoint.')

DELTA_SCHEMA = dict(anyOf=[obj({}, description='Explicit no-change commit.'), obj(dict(
    plan_header=obj(dict(valid_until=dict(type='number'), freeze_until=dict(type='number'), reason=ID),
                    description='Decisions only; harness supplies version, created_at and scope.'),
    tasks=patch(TASK, TASK),
    holds=patch(HOLD, obj(dict(ref=ID, hold=HOLD))),
    machine_orders=array(obj(dict(machine=dict(type='integer'), task_ids=IDS),
        description='Full resulting queue on each changed machine. Each new/replaced task appears exactly once; retained tasks may move.'))))])


def model_task(task):
    """Project an internal task without modifying it."""
    return {k: deepcopy(v) for k, v in task.items() if k not in ('machine', 'lot_ids', 'steps', 'visits')}
