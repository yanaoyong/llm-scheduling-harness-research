要求：
- 使用网络搜索。优先：Agent 框架/编码 agent 的官方文档与工程博客（Anthropic、OpenAI、Google、Manus、Cognition、Cursor、Sourcegraph、OpenHands、SWE-agent、Aider、LangChain/LangGraph 等）、2023–2026 年论文与可复现的评测。
- 每条结论给出来源标题与 URL；明确区分"来源原文说的"与"你的推断"。不要编造来源或数字；找不到就写找不到。
- 有量化数据（token 节省比例、准确率变化、成本）的尽量给出原始数字和实验条件。
- 最后一节"对我们问题的可借鉴做法"：结合 _context.md 的约束，逐条给出具体可实现的设计建议，并说明它是否满足"不静默丢弃工作"约束、对 token 和请求次数的预期影响。
- 中文 Markdown，3000–6000 字。只做调研与输出文本，不要修改仓库里的任何文件。
