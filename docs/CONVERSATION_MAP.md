# Codex 会话地图

本页列出 8 个主会话的人工摘要；它们只是重点导航，不是归档覆盖总数。Owner 规范快照覆盖 98 个相关持久化会话（8 个主会话及相关会话），共 5,035 条可见消息。完整范围、分类与截止时间以 [conversations/index.json](../conversations/index.json) 为准。规范正文请使用每行提供的 transcript `.md` / `.jsonl` 链接；`notes/` 内先前生成的导出仅作辅助，不是权威导出。规范导出不含隐藏推理。

| Thread ID | 主题 | 与项目关系 | 归档摘要 |
|---|---|---|---|
| `01a12e07-fae5-70c2-ad30-c126f1f1b178` | 分析 Codex 工厂数据排程的缺陷 | 从 SMT2020 B 方案问题转入 M0.5、相近项目调研、harness 草案；最新转向归档。 | [主会话摘要](../conversations/notes/01a12e07-fae5-70c2-ad30-c126f1f1b178.md) · [规范正文 MD](../conversations/transcripts/01a12e07-fae5-70c2-ad30-c126f1f1b178.md) · [规范正文 JSONL](../conversations/transcripts/01a12e07-fae5-70c2-ad30-c126f1f1b178.jsonl) |
| `01a12f91-839a-7c20-966e-c689ec30391a` | 检查 Codex 会话是否偏移 | 另一会话的任务/上下文核验。 | [主会话摘要](../conversations/notes/01a12f91-839a-7c20-966e-c689ec30391a.md) · [规范正文 MD](../conversations/transcripts/01a12f91-839a-7c20-966e-c689ec30391a.md) · [规范正文 JSONL](../conversations/transcripts/01a12f91-839a-7c20-966e-c689ec30391a.jsonl) |
| `01a129dc-8ced-7071-9f77-f1038e8df2f8` | 修复 B 记忆超限与重复读页并恢复排程 | 直接排程长运行的故障诊断、修复与续跑；最终完成 B 的 0—3600 秒全厂窗口，10/12 B 结果报告汇总质量和成本。803.25 秒仅为旧会话早期检查点。 | [主会话摘要](../conversations/notes/01a129dc-8ced-7071-9f77-f1038e8df2f8.md) · [规范正文 MD](../conversations/transcripts/01a129dc-8ced-7071-9f77-f1038e8df2f8.md) · [规范正文 JSONL](../conversations/transcripts/01a129dc-8ced-7071-9f77-f1038e8df2f8.jsonl) |
| `01a12393-b066-79e3-ad84-0ee36b45d691` | 查看另一个 Codex 会话进度 | 持续检查 B 运行是否停滞、重复调用及优化恢复情况。 | [主会话摘要](../conversations/notes/01a12393-b066-79e3-ad84-0ee36b45d691.md) · [规范正文 MD](../conversations/transcripts/01a12393-b066-79e3-ad84-0ee36b45d691.md) · [规范正文 JSONL](../conversations/transcripts/01a12393-b066-79e3-ad84-0ee36b45d691.jsonl) |
| `01a11fc6-3c70-7380-aadd-4a88dbd97d58` | 推进 SMT2020 全厂排程实验 | 推进 SMT2020 全厂试验；后续关注从两台受控设备扩展到全厂决策。 | [主会话摘要](../conversations/notes/01a11fc6-3c70-7380-aadd-4a88dbd97d58.md) · [规范正文 MD](../conversations/transcripts/01a11fc6-3c70-7380-aadd-4a88dbd97d58.md) · [规范正文 JSONL](../conversations/transcripts/01a11fc6-3c70-7380-aadd-4a88dbd97d58.jsonl) |
| `01a11e71-9b95-76c1-97d9-db087c25bc4c` | Read Codex goal objective | 第二轮三数据集实验与后续 SMT2020 设计反思；识别两台设备控制的外推限制。 | [主会话摘要](../conversations/notes/01a11e71-9b95-76c1-97d9-db087c25bc4c.md) · [规范正文 MD](../conversations/transcripts/01a11e71-9b95-76c1-97d9-db087c25bc4c.md) · [规范正文 JSONL](../conversations/transcripts/01a11e71-9b95-76c1-97d9-db087c25bc4c.jsonl) |
| `01a11bce-5043-7871-b0e3-cd5f4e9f2393` | 完成半导体排程三方案对照实验 | 第一轮 A/B/C 小实例实验、公开基准值讨论，并提出扩展数据集。 | [主会话摘要](../conversations/notes/01a11bce-5043-7871-b0e3-cd5f4e9f2393.md) · [规范正文 MD](../conversations/transcripts/01a11bce-5043-7871-b0e3-cd5f4e9f2393.md) · [规范正文 JSONL](../conversations/transcripts/01a11bce-5043-7871-b0e3-cd5f4e9f2393.jsonl) |
| `01a11e71-36be-7c72-8e34-6e223f43fcb4` | 已归档无短标题任务附件会话 | 保存第二轮实验目标的粘贴附件相关会话。 | [主会话摘要](../conversations/notes/01a11e71-36be-7c72-8e34-6e223f43fcb4.md) · [规范正文 MD](../conversations/transcripts/01a11e71-36be-7c72-8e34-6e223f43fcb4.md) · [规范正文 JSONL](../conversations/transcripts/01a11e71-36be-7c72-8e34-6e223f43fcb4.jsonl) |

## 推荐阅读顺序

1. 第一轮静态方案对比：`01a11bce…`。
2. B 的 SMT2020 长运行与恢复：`01a12393…`、`01a129dc…`。
3. 第二轮实验和控制范围反思：`01a11e71-9b95-76c1-97d9-db087c25bc4c`、`01a11fc6…`。
4. 当前综合研究与归档需求：`01a12e07…`。

每个同名 `.jsonl` 文件提供可见消息摘录；每条记录带原 rollout 行号、UTC timestamp、speaker 和原文。原始 rollout 仍是出处，摘录不是完整原始日志。
