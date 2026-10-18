主题一：主流 agent harness 如何处理"环境状态远大于上下文窗口"。
调研：
1. 预加载 vs 即时检索（just-in-time / progressive disclosure）：Claude Code、Codex CLI、Cursor、Aider（repo map）、Sourcegraph Cody、OpenHands、SWE-agent（ACI 设计）、Devin 等如何决定放进上下文的内容；"摘要 + 指针/句柄 + 查询工具"的做法。
2. Anthropic《Effective context engineering for AI agents》、长时任务 harness 相关博客、Manus《Context Engineering for AI Agents》经验（KV cache 命中、文件系统作外部记忆、工具结果保留/遮蔽等）、OpenAI Agents/Codex 相关指南、LangChain 对 context engineering 的分类（write/select/compress/isolate）。
3. 子 agent / 多 agent 隔离上下文（按子任务拆分、主 agent 只收摘要）的收益与代价，以及各家对协调问题的处理。
4. 用检索/工具替代全量上下文时，如何保证不遗漏（计数、清单、覆盖校验、"未处理项"列表等）。
5. 工具调用轮数 vs 上下文大小的取舍：有无数据比较"大上下文一次给完"与"小上下文多轮查询"的成本与质量。
