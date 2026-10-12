# 冻结清单修正记录

2026-10-09，在任何正式记录启动之前，主Agent核对冻结矩阵时发现第一次辅助清单生成命令遗漏 --auxiliary，得到108个ABC格点，而协议规定36个F格点。未执行任何该错误清单下的运行。

原清单内容原封不动移动至 configs/freezes/deprecated/static-aux-v1.json，freeze-static-aux-v1标签保留；不是删除失败或历史改写。新增static-aux-v2清单与独立标签，仍使用预定auxiliary_static_v1结果phase、相同已提交算法/配置及36个F格点。主核心static-v1不变；不涉及查看正式结果后调参或选题。
