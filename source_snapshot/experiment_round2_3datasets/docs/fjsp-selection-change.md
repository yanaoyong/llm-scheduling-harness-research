# 开发集扩充记录（任何正式运行前）

主 Agent 指令增加 mk10，只进入 development。原开发集 mk01/mk02 仅55/58工序，不能覆盖正式 mk08 的225工序输出规模；mk10 用于大规模 B 输出/调用预算探测。选择理由是预先可读取的规模，未查看 mk10 的 A/B/C 成功率或排程结果。正式 mk03/mk05/mk08 与 Hurink la02/la06/la11 e/r/v，预留 mk04/mk06/mk09 与 la03/la07/la12 e/r/v 全部保持。

源角色没有运行模型或求解器。原32集 source-lock、manifest、split、参考值完整归档于 `docs/fjsp-selection-v1/`。现行清单扩为33个实例并重新校验；原32个标准输入内容没有修改。
