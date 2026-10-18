主题二：结构化/表格数据给 LLM 时的表示与压缩，以及长上下文的实际可用性。
调研：
1. 表格/结构化数据的格式对 token 数与理解准确率的影响：JSON vs CSV vs Markdown 表 vs YAML vs 列式/表头一次 vs TOON 等新格式；有无基准（如表格问答、结构化数据理解基准）给出数字。
2. 字典编码/ID 化、分组聚合（相同属性的条目合并为"类别 + 成员列表"）、差分（只发变化）等手段的 token 节省与对模型准确率的影响。
3. 提示缓存（Anthropic prompt caching、OpenAI 自动缓存、Gemini context caching）：对固定前缀的计费与延迟效果、缓存命中条件、前缀稳定性要求；以及"缓存只降成本、不减少上下文占用"这一点各家文档怎么说。
4. 长上下文退化：Chroma "Context Rot"、NoLiMa、RULER、Lost in the Middle、各模型有效上下文长度 vs 标称长度、"针多" 场景（需要逐条处理上千条记录）下的表现。几十万 token 的结构化状态给模型做全量决策是否现实。
5. OpenAI/Anthropic 对单次请求输入上限、工具结果大小的官方说明。
