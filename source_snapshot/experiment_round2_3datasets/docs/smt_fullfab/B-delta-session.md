# B 差量会话原型：显式查询、检查与一次性选择

`src/smt_fullfab/delta_session.py` 是隔离的纯内存会话模块。它尚未接入 B/C 控制器，不调用模型、环境、CP、经典构造器或物理审计，不提交计划、不推进时钟、不登记预算。当前运行和冻结结果均不受影响。底层编译规则继续使用已提交的 [`plan_delta.py`](../../src/smt_fullfab/plan_delta.py)，没有修改该文件。

目的在于允许模型引用准确 base 任务、按需读取当前观察，再显式提交计划差量，减少每次局部事件后重新输出全厂所有页任务的需要。此处没有测量真实 token、调用数、总墙钟或排程质量，也不预设该接口优于全页方式。

## API 与会话边界

```python
session = DeltaSession(
    base_plan, problem, execution_state,
    source_sha256=source_sha256,
    paging=complete_compact_v2,
)
catalog = session.describe()
response = session.handle(action, call_id=call_id, model_index=model_index)
archive = session.export_evidence()
```

仅接受 JSON 数据和上述权威输入。`paging` 必须是含 `pages` 的完整 `fullfab-compact-paging-v2` manifest。初始化调用纯 `expand_pages` 校验全部页、词典和源索引，再核对还原 problem 与传入的权威 problem 的准确 JSON hash；缺页、重复/冲突行、源 hash 不匹配均拒绝，不生成缺失页。分页自己的 `source_problem_sha256` 使用 v2 定义的非 ASCII 转义规范，四锚中的 problem hash 使用 `plan_delta.json_sha256`；两者不混用，而以完整还原后的 JSON 内容连接。

完整还原也不足以验证未被解码使用的顶层文字。因此构造器另外封闭 v2 顶层允许字段：只允许已发布的 schema/字段说明/字典说明/完整页/计数/problem 元数据/source hash，以及与 problem 精确对应的 `time,horizon_end,scope,setup_transitions,min_runs` 镜像。`operation_identity` 和 `dictionary_semantics` 必须与发布的 v2 固定说明文字完全一致。唯一支持的外层扩展是可选 `observation_end`，它须与权威 state 的同字段保持准确 JSON 值和数字表示；`page_count` 必须是准确整数并等于实际页数。未知字段（例如 `ranked_recommendations`）、改写说明为“优先选最高优先级”等内容、伪造观察终点均拒绝，不能借未解码的 metadata 向模型夹带推荐。原 problem 本身的完整字段仍按权威输入原样还原，不进行内容筛选。

会话复制所有输入，不持有可被调用方修改的原字典。`session_id` 由版本、四锚及准确分页 hash 确定，是**内容定义的逻辑会话身份，不是唯一运行实例编号**。四锚是 `base_plan_sha256,problem_sha256,state_sha256,source_sha256`。新观察必须新建会话，没有更新当前状态或导入外部候选的入口；旧候选不进入新对象，即便输入快照完全相同也要重新显式检查。但是，相同内容创建多个对象会得到相同逻辑 session ID，各对象独立检查后也可能生成相同候选；本模块没有跨实例调用去重或执行登记。本模块无法读取真实工厂状态，外层仍必须在共同 commit 前，用当时真实状态再次核对四锚，不能用旧会话的成功结果冒充新观察。

`describe()` 是供外层原样交付并保存的初始目录，不冒充一次模型动作。目录包含完整 v2 元数据和全部页索引、原 base header、执行状态、全部 base 任务 IDs、全部未派工 IDs、全部 hold refs、全部 operation IDs 和动作字段定义。目录按原数组顺序列出，不按优先级、交期或可行性选取。已经过期或工序已不在当前 problem 的 base pending 身份仍可查询；查询不会把它们自动修正、取消或删除。

## 明确动作

所有动作都必须精确包含 `action,session_id,anchors` 和下表列出的专属字段。未知动作或多余字段拒绝，没有默认动作。

| action | 专属字段 | 行为 |
|---|---|---|
| `read_page` | `page_index` | 返回模型指定页的完整原 compact 数组和完整分页元数据；可任意顺序、重复查询 |
| `read_base_tasks` | `task_ids` | 返回指定的准确 base task 原字典，包括全部未知字段；附原索引和已派工标记 |
| `read_base_holds` | `hold_refs` | 返回指定的准确原 hold，引用格式由目录明确列出为 `h:0` 等 |
| `read_operations` | `operation_ids` | 返回指定的完整当前工序原字典，不解析 operation ID 或推导字段 |
| `read_candidates` | 无 | 返回全部已成功检查候选的摘要，按检查创建顺序；没有默认或推荐候选 |
| `read_candidate` | `candidate_id,candidate_sha256` | 返回该候选完整原 delta、全部编译结果/证据、检查动作来源及状态绑定 |
| `check_delta` | `delta` | 仅调用一次纯 `compile_plan_delta`，保存候选或完整拒绝诊断，不选择、不提交 |
| `apply` | `candidate_id,candidate_sha256` | 由后续明确动作选择本会话已检查候选；只返回 `selection_for_external_commit` |

引用查询严格按模型给出的 ID/ref 数组顺序返回，保存每个原字段、缺失与 null 的差别、原数组顺序和数值类型。不存在的引用、重复引用和非法页索引拒绝整次查询，不返回部分答案、不替换相近工序。空引用数组是模型明确选择的空查询。所有合法页及未派工 base 身份均可见，没有系统挑选的候选子集或质量排序。

所有查询都不会调用差量编译器。模型可选择读取整个 problem，也可按目录仅读取某些页/引用；这个原型不认证模型已看过全部上下文。外层必须保存初始目录的真实交付、每次查询输出和实际模型请求，才能说明它实际获得了什么信息。

## 检查与选择分离

`check_delta` 成功只返回摘要：候选 ID/hash、四锚、原检查动作索引/call ID/model index、delta hash、编译计划 hash、任务/hold 数量。数量只是完整性信息，不是收益评分。完整候选保存在会话中，可经 `read_candidate` 明确查询，也完整包含在 `export_evidence()`。候选 hash 覆盖完整候选，包括原 delta、所有编译证据及检查来源，不仅覆盖计划摘要。

正常编译拒绝返回原 `DeltaError` 的 code/detail；会话记录原动作和拒绝，不自动调整 `not_before`、删除困难任务、替换设备、补 hold 或生成另一候选。意外编译异常也只记录类型和消息，无隐式重试或备用算法。原模型输出若根本不是有效 JSON，仍须由外层 transport 保存；非 JSON Python 对象在本模块入口抛错，不能伪装成已记录的 JSON 动作。

`apply` 必须是检查之后另一个明确动作，使用新的 call ID 和更大的 model index，并精确选择已有候选的 ID/hash、相同 session ID 与四锚。不允许在 apply 中同时传入新 delta、修改候选或选择“最佳”“最新”。它不会调用环境 commit，返回值明确为：

```json
{
  "status": "selection_for_external_commit",
  "physical_commit_performed": false,
  "model_attribution_certified": false,
  "external_common_validation_required": true
}
```

实际返回还包含准确候选、选择动作和全部状态绑定。**一旦选择，该内存对象终止所有后续动作**：不能再次 apply、改候选或继续查询。后续尝试仍记录为拒绝；原 selection 保持不变。这项一次性限制仅对象内有效，不能阻止调用方另建对象重复检查/选择。外层必须持久化登记逻辑会话与实际执行实例，并在共同 commit 时防重复，不能把本模块当作已经完成跨实例防重。外层共同 commit 若拒绝，本原型不自行修订或继续；反馈、修订次数、恢复和新会话规则需由后续版本明确实现。`selection_for_external_commit` 永远不是物理提交成功或已完成生产的声明。

## 历史证据与尚未实现的控制器责任

每次 JSON 动作尝试都有连续 `action_index`，原 `call_id,model_index`、原动作及其 hash、原响应及其 hash、四锚和前一条历史 hash。正常动作要求 call ID 未用过、model index 为严格递增的非负整数；重复、倒退或 bool 伪装整数会留下拒绝记录，不重新执行编译。已使用的合法 call/index 身份即使动作被拒绝也不会被当作新调用重试。

这些字段仅在当前对象内做一致性检查。本模块不查询模型服务，不核实 token/费用，也不认证 call ID 对应真实请求；另一实例可以再次接受相同 call ID/model index。目录显式标注 `call_uniqueness_scope` 与 `selection_once_scope`。历史 hash 链只能绑定本次导出的内容，不能独自证明模型归属或防止外部伪造另一条链。

`export_evidence()` 返回独立副本，包含全部原输入、完整分页、初始目录、查询/检查/拒绝/选择历史、全部候选与一次性 selection。当前没有文件写入、持久化恢复、自动重放或实际模型循环；不得将对象重建误称为可恢复真实运行。后续控制器仍需实现：

1. 持久化登记逻辑会话、实际运行实例和已有选择，阻止重复实例执行；绑定真实 transport 请求/原输出、call ID 与这里动作索引，并 append-only 保存所有拒绝，不能只保存最终成功选择。
2. 页查询、模型响应、编译时间、日志和累计资源的预登记与计费；当前原型不表示这些动作免费。
3. 对当时真实状态重新核对四锚，再调用共同 validator/commit，并保存准确提交结果。不得把选择返回值直接算作 dispatch。
4. 独立重建差量来源与选择链，并执行物理、冻结、覆盖机会等完整审计；不能把复用编译器当作独立归属证明。

这里没有 COND 自动取消或后台补排，B 也没有经典优化接口。任何后续真实对照必须先冻结控制器版本与独立审计，本原型测试不计为真实 B 的阶段验收。

## 轻量验证

```sh
.venv/bin/python -m unittest tests.test_smt_fullfab_delta_session -v
```

27 项纯字典测试覆盖完整 v2 绑定、顶层推荐/固定说明篡改、观察终点与页数镜像、任意页查询、未派工身份可见、原始未知字段/null/数组序、无隐式修复、检查/选择分离、候选摘要及完整证据、选旧候选、四锚与候选 hash、跨状态隔离、对象内重复 call 与一次性终止、跨实例限制声明、所有拒绝历史与 hash 链、外部修改输入/返回值不影响会话。未读取真实 B 状态，未调用模型、环境、求解器或工厂仿真。
