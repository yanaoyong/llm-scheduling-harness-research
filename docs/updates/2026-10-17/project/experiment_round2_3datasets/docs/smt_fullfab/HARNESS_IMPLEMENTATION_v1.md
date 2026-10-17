# Harness v1 实施记录

目标：HARNESS_DESIGN_v1_20261013.md 的 P0–P5；P6/P7 仅交付配置和计划。

当前交付代码为 `scheduling-harness-v1.1.0-offline`，协议为 `scheduling-harness-v1.1`。真实 P5 使用的 v1.0 冻结版本已失败封存；修复版尚无真实模型验收。最终结论及资源账目见 [P0–P5 验收报告](HARNESS_ACCEPTANCE_P0_P5_20261014.md)。G5 未通过，目标未完成。

修复版 197 项完整测试及随后补充的 2 项恢复/优化器边界测试（合计 199 项）、实际启动/恢复/审计，以及旧冻结试点的停止命令集中记录于 [实际命令与离线复现](../../artifacts/harness_v1_1_offline/actual_commands.md)。

基线提交：6929dd8cb624d95b85d374e6a697025b93af4fc5。开始时四个历史 progress 文件已修改，另有历史未跟踪证据；清单固定在 `artifacts/harness_v1_development/baseline/git_status.txt`。不覆写这些文件。源码、依赖、配置、数据及设计引用的 823 个文件指纹见同目录 fingerprints.json。设计 S01–S08、C01–C16 的所有给定内容指纹与当前文件一致。未发现适用的磁盘 AGENTS.md，遵循用户提供的环境说明；只读进程检查未发现活动排程实验。

实施顺序及当前状态（结论以实际测试产物为准）：

|阶段|交付|出口|
|---|---|---|
|P0|版本契约、配置、语义和映射|所有动作有明确拒绝与归属规则|
|P1|原子提案、分块、候选、独立 apply、字段来源|新旧编译等价与负控|
|P2|实体版本、分页、依赖失效、精确原件|完整重建与缺页检测|
|P3|事务运行头、事件、累计预算、租约、恢复入口|真实中断后继续提交与推进|
|P4|固定证据、独立来源/物理/机会/成本、统一报告|正负控与外部账本追加稳定性|
|P5|>=20 预登记片段，至多一条全新 B 一小时|G0–G4 先通过；预算及准入独立冻结|

契约以 `src/smt_fullfab/harness/contracts.py` 为唯一协议常量源。私有工厂状态、公开上下文、模型决定/笔记、运行控制分别存储；模型只通过公开引用读取事实，不能写物理头或预算。所有模型/经典尝试在可信宿主中分配身份；业务 request_id 由决定者声明。

|不变量|实施检查点|验证|
|---|---|---|
|I01|transport 禁用原生工具；gateway 引用白名单|T14|
|I02|候选逐字段来源、明确选择、commit、dispatch 链|T01/T23|
|I03|仅适配原纯 compiler，缺字段拒绝|T01–T05|
|I04|检查与 apply 使用不同较晚的输出身份|T06|
|I05|context revision + commit CAS|T07|
|I06|旧编译器冻结前缀、准备态提交检查|T03/T04/T18|
|I07|完整 scope、gap/hold 边界|T05/T22/T25|
|I08|commit 与 execution 独立事件及计数|T18/T22|
|I09|attempt 预留/发送/结算，resume 同账户|T15/T16/T20/T28|
|I10|UNKNOWN 冻结，不填零，不盲重发|T13/T15/T17/T26|
|I11|只读封存证据及独立检查器|T21/T23/T24|
|I12|manifest 指纹和版本门禁|T20/T27|

G0 对应契约；G1 对应 T01–T09/T14；G2 对应 T10–T13；G3 对应 T15–T21/T27/T28；G4 对应 T22–T26 以及来源/物理/成本负控；G5 必须另有真实模型微基准与完整一小时证据，离线测试不能替代。

语义保持 partial：CQT 未实现；历史绑定资料缺失保持 undetermined；名义残余使用既有公开预测；冷启动不等于完整现场初态；官方数值校准和在线能力未验收。完整生产责任范围保持 913 台。

设计落实说明：新增公共层复用现有纯编译、分块组装、公开观察和独立事件审计；持久权威头采用 SQLite 事务，内容寻址对象先 fsync 再发布引用，trace 为可重建投影。操作系统独占锁加递增 fencing token 防并发与旧写者。第一版采用每次物理事务的完整当前状态对象（不含重复 trace），trace 按事件保存；查询不复制物理状态。该方式优先验证恢复正确性，长窗存储性能在 P7 另验。

初始 CLI 盘点记录为 PATH 中的 `codex-cli 0.147.0`；实际模型实验使用后文所述随附 `0.162.0-alpha.17.2`。支持并验证了 `exec --json --ephemeral --ignore-user-config --ignore-rules --sandbox read-only --output-schema --output-last-message`。官方参考：[Developer commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli)。隔离验证和真实试点分别保留证据。

预算采用本次 goal 新授权，历史专项额度不继承：微基准 100 次 / 2M token / 1h 模型 / 2h 总墙钟；全新 B 250 次 / 6M / 3h / 4h；合计 350 次 / 8M / 4h / 6h。CLI 无可核实精确 token 硬上限时保守预留并披露；未知用量冻结新调用。单次 <=600 秒，不自动重发。

## 已实现的运行入口与证据边界

入口：`.venv/bin/python -m src.smt_fullfab.harness`，子命令为 `config`、`start_new`、`resume_run`、`fork_scenario`、`action`、`run`、`stop`、`status`、`audit`。P5 编排入口为 `.venv/bin/python -m src.smt_fullfab.harness.p5`，依次提供 `prepare`、`register`、`micro`、`full`。`prepare` 不推理；`register` 要求冻结源码对应的 G0–G4 报告；`full` 要求完整微基准门槛通过且尚未使用唯一的新 B 运行身份。`resume_run` 不隐式发送模型请求；已持久响应只重放解析/业务处理，发送但未结算的尝试保留 UNKNOWN。

实际执行记录在 `artifacts/harness_v1_development/cli_*.log` 与 `entrypoint_help.txt`、`p5_help.txt`：

```sh
.venv/bin/python -m src.smt_fullfab.harness start_new artifacts/harness_v1_development/cli_smoke --config configs/smt_fullfab/harness_v1/C-fixed_3600.json --experiment-id offline-cli-smoke --mode policy
.venv/bin/python -m src.smt_fullfab.harness resume_run artifacts/harness_v1_development/cli_smoke
.venv/bin/python -m src.smt_fullfab.harness run artifacts/harness_v1_development/cli_smoke --steps 2
.venv/bin/python -m src.smt_fullfab.harness stop artifacts/harness_v1_development/cli_smoke --reason offline_cli_stop
.venv/bin/python -m src.smt_fullfab.harness audit artifacts/harness_v1_development/cli_smoke --output artifacts/harness_v1_development/cli_smoke_audit
.venv/bin/python -m src.smt_fullfab.harness config --arm C-fixed --seconds 60
.venv/bin/python -m src.smt_fullfab.harness start_new artifacts/harness_v1_development/cli_positive --config artifacts/harness_v1_development/offline_60_config.json --experiment-id offline-cli-positive --mode policy
.venv/bin/python -m src.smt_fullfab.harness run artifacts/harness_v1_development/cli_positive --seal
```

第一条 smoke 特意在提交后、物理推进前停止，独立审计正确给出未完成整窗；第二条正例完成 60 秒，独立来源、物理、机会和成本检查均通过。它们都是离线策略夹具，不是 B 或真实模型实验。运行目录使用 create-new 语义，以上已存在路径不能重新 start_new。新试验须另选目录，P5 则由注册器分配固定目录。

以上旧目录记录的是当时 v1.0 的实际命令，不能用修复版直接恢复。真实冻结版本连同数据、依赖锁、旧配置和原测试已保存为 `artifacts/harness_p5_v1_release/frozen_source/source-and-data.tar.gz`，逐文件索引为同目录 `index.json`。如需复核旧版本，应解包至独立目录；不要覆盖当前修复代码或原运行。

## P5 失败及离线修复

登记集合为相同 V14 历史来源中的 20 个小修订片段；筛选依据与初态在推理前固定。试点实际启动 3 个，调用数为 10、10、1；接受数为 0。所有 21 条实际输出都是读取当前相同 `context_ref` 的 `get_context`。第三个片段在发现缺陷后通过 stop 入口请求停止，在途结果完成结算后封存。其余 17 个不补零作为完成延迟、不剔除、不替换。原 `micro_gate.json` 保留其原始计数投影，但其中未启动项的 0 不能解释为 0 轮完成；完成延迟中位数和 P95 不可估计，整组 fail。

真实成本为输入 853,160、输出 1,719，共 854,879 token；缓存输入 9,216 已包含在输入中，不重复加计。21 次尝试，模型活动 504.521 秒，实验至必要审计闭合墙钟 548.916 秒；未知用量为 0，金额未知。完整 B3600 未启动。原始请求、schema、事件、响应、父进程守卫、SQLite 账本、封存边界及独立审计保留在 `artifacts/harness_p5_v1_release/runs/micro-01` 至 `micro-03`。

确认的工程缺口：相同成功读取未执行设计第 6 节的协议无进展停止规则；实际提示只含最近一次结果，没有可读的既往动作链。缺少动作历史可能促成循环，但没有新鲜对照，不能断言这是唯一原因，更不能宣称修复版已改善模型表现。

修复版增加本运行自身动作和工具结果的持久公开索引，最近 8 条可内联，较大原件及完整历史均通过受控引用精确读取；原始非 UTF-8 字节使用显式 base64 表示，不替换字符。提示明确当前 context 已交付。相同物理修订下连续相同读取在第二次反馈原件和计数，达到预先配置的 `same_read_limit=3` 时停止；不同分页、投影或新物理修订独立计数。幂等重放不会重复计数。该控制不选择机器、任务、批组、顺序或候选。

协议、配置和源码指纹均已变更；旧冻结运行拒绝直接恢复。新配置另存 `configs/smt_fullfab/harness_v1_1_offline/`。修复只经离线测试，不与旧失败轨迹拼接。红灯回归保留在 `artifacts/harness_v1_development/test_history/15_p5_regression_red.log`，完整修复版测试、实际 CLI 本机模拟通道、运行及审计记录位于 `artifacts/harness_v1_1_offline/`。

## 与设计基线的具体落实和修订

- 编译、观察、物理执行、旧 V7–V15 控制器保持原文件；新 Harness 调用纯模块并以独立 SQLite 事务管理权威状态。历史记录未用来写新状态。
- 实体依赖采用完整公共观察 epoch，时钟和竞争资源变化均使实体版本失效。这比细粒度缓存保守，但没有隐藏截断、候选排序或遗漏依赖。完整目录/原件始终可查。
- 大提案分块复用原组装器，保留明确版本和已接受 chunk；相同 chunk 内容幂等，冲突拒绝。宿主只绑定 schema/anchors 等技术字段，生产字段均来自原始输出/显式保留基准。
- `C` 的全局 CP 工具从显式参数开始独立搜索；传入 candidate 作为已登记比较基准，不声称它是暖启动或保证改进。超时、NO_RESULT、UNKNOWN 都不生成隐式后备计划。
- `A`、`C-fixed` 当前接入的是明确登记的固定构造策略，足以验证公共适配契约，但尚不是经容量/参数标定的强 A 基线。P6 明确以前置容量检查补齐，不能据此声称模型胜过经典算法。
- 中途片段的来源/机会检查仍使用原始计划窗口；独立低层物理复算只把“已到期事件”截止点设为保存头的已观察时刻。不会追加伪造 terminal，`execution_window=fail`、`physical_validity=false` 仍保留，另给 `physical_prefix_checks` 和 `fragment_acceptance`。这只支持小修订片段验收。
- 首次必要审计通过 `audit_closure.json` 固定实验成本墙钟。以后复查继续从封存原件重算，复查日期和其他运行账本不会改变原实验费用。
- 工程状态来自同一个 `acceptance.json` 投影生成 `STATUS.json` 和报告；单运行审计不自行宣称 G5，G5 由已注册微基准及唯一 B3600 的实验级门槛联合判定。

## Codex 通道实际核实

PATH 中 npm CLI 为 0.147.0，目录不包含既定模型。实际冻结选择历史运行器使用的 ChatGPT 随附二进制 `codex-cli 0.162.0-alpha.17.2`，直接路径 `/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex`。固定 `gpt-6-astra / medium`，从这套 CLI 的原生模型目录冻结对应元数据，排除账户 identity；不凭旧缓存拼补缺字段。

用户配置、规则、原生 shell、MCP、Apps、插件、浏览器、图像、技能自动注入、其他 agent、原生计划/询问工具都在通道配置中关闭。沙箱为 read-only。模型只获得公共事实和受控业务结果。隔离证据采用真实 CLI 连接本机确定性 HTTP 模拟服务，记录实际请求体：模型为 gpt-6-astra，原生工具为空，技能目录未注入。损坏响应负例仅发生一次 HTTP 请求，退出失败且不重连。模拟数据不属于真实模型额度。

内置 provider 不允许覆盖重试参数，因此使用指向官方 ChatGPT Codex endpoint 的命名配置，继续由 CLI 使用原登录，显式 `request_max_retries=0`、`stream_max_retries=0`；不读取/复制 OAuth token，不更换账户。配置依据及实际验证分别见 [官方配置 schema](https://learn.chatgpt.com/docs/config-schema.json) 与 `artifacts/harness_v1_development/cli_preflight/`。单次原始 prompt/schema/模型元数据、输出/usage、进程启动/结束/父进程 wait 证据全部绑定内容哈希；成本审计从这些原件复算输入/输出/缓存和活动时间。

## 后续实验

`configs/smt_fullfab/harness_v1/P6_P7_plan.json` 及四臂 3600/28800/86400 秒配置可加载。P6 的十二条轨迹和 P7 长窗均未获执行授权，配置保留原一小时费用上限，不按时窗长度自动扩额。后续须先通过 G5、强 A 容量与 C 恢复/参数审查，冻结共同初态和十二个身份，再单独授权资源。在线旧计划继续、迟到候选与截止期策略仍是新协议范围。
