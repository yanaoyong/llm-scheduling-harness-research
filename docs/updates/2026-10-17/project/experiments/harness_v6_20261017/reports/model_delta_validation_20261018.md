# Phase M：决策 delta 的离线验证

新协议只传模型决策；不改 env_adapter、executor、ledger、store、normalize。
`tests/test_model_delta.py` 覆盖完整内部任务等价、当前工序身份展开、保留任务移动、
完整机台队列、非法重复字段、共享完整 schema 与条件 hold。
继承的 29 个 plan_delta 测试全部保留；不再存在的 keep/anchors/header 冗余字段
拒绝测试改为禁止旧字段，取消和替换改为单列表及显式完整队列。

使用既有 configured 环境及 `tiktoken` o200k_base，确定性紧凑 JSON：

| 输入 | 旧 tokens | 新 tokens | 旧 bytes | 新 bytes |
|---|---:|---:|---:|---:|
| scripted_delta，首周期 | 460 | 166 | 1144 | 440 |
| G0 全部 26 项 base task 表达为 delta | 4063 | 1106 | 9205 | 3169 |

G0 时间 1649.8155803370928。新旧对比使用同一组决策；旧格式包含 schema、
order_policy、四项 anchors、完整 header、keep 及任务重复身份/机台。
G0 整个 base 转换为 add 仅用于大小对比，并非对原 base 重复提交。
命令：`scripts/measure_model_delta.py --database <contexts.sqlite> --output <report.json>`。
输出在 `/workspace/v6-mac-env/work/model-m-tokens.json`。

最终完整 plain/configured suite、sealed validation、P2、compileall、diff 检查及
继承测试逐项变更理由记录于 `/tmp/v6orch/PHASE_M_REPORT.md`。
新版本由 host 生成，版本字符串及其依赖哈希会改变；物理字段相等必须另行比较。
F6 的 12 项 live Codex 探针仍未运行，CQT/Q-time 仍未实现。
