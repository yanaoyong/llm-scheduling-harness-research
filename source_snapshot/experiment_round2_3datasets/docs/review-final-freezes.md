# 最终冻结与 Git 版本独立核验

核验日期：2026-10-09。结论：**通过，errors=[]**。

独立脚本：`scripts/final_freeze_review.py`。输出：`artifacts/final/qa/freeze_git_review.json`。脚本只使用 Python 标准库读取文件与 Git，不导入现有 replay、运行器、模型、求解器或仿真模块；没有修改冻结材料、原始结果或既有报告。

复跑命令：

```sh
.venv/bin/python scripts/final_freeze_review.py
```

脚本只允许覆盖自己的 QA JSON。退出码 0 表示本次版本检查通过；退出码 1 表示存在具体错误。逐冻结、逐运行的错误及文件期望/当前/Git SHA 均写入该 JSON。

## 冻结检查

| 冻结 | 标签 | 代码 commit | 文件条目 | 结果 |
|---|---|---|---:|---|
| static-v1 | freeze-static-v1 | 9ae3b700006f4d3a8d7169aab165e95a0ae48023 | 72 | 通过 |
| static-aux-v2 | freeze-static-aux-v2 | f8b91fa9be7b1f2fb19481ae6090abec8dccb4af | 72 | 通过 |
| smt-v1 | freeze-smt-v1 | 248ed415177ddd0741f9061c668bdd841e24ac42 | 51 | 通过 |
| smt-aux-v1 | freeze-smt-aux-v1 | 248ed415177ddd0741f9061c668bdd841e24ac42 | 51 | 通过 |
| static-channel-recovery-v1 | freeze-static-channel-recovery-v1 | c6c37905cf512c208d48521664ab3386a8772abe | 76 | 通过 |

所有标签解析到各自声明的真实 commit。322 个冻结文件条目逐一验证：声明 SHA = 当前文件 SHA = 对应 commit 的 Git blob SHA；跨冻结重复条目仍分别核对。两个 SMT freeze 的外部数据清单均与当前完整 20 文件及其哈希一致。

恢复 freeze 为原 static-v1 的 72 个文件，保持原 SHA，另加恢复协议、恢复 manifest 和两个恢复脚本，共 76 个。恢复标签明确指向 `c6c3790`，没有拿最终 HEAD 替代历史执行 commit。

## 运行版本检查

| 阶段 | 冻结矩阵记录 | 版本关联通过 |
|---|---:|---:|
| acceptance_static_v1 | 108 | 108 |
| auxiliary_static_v1 | 36 | 36 |
| acceptance_smt_v1 | 27 | 27 |
| auxiliary_smt_v1 | 9 | 9 |
| recovery_static_channel_v1 | 1 | 1 |

核对内容包括：矩阵及目录集合、run/instance/scenario/arm/repeat 身份、code_commit/tag、保存的 freeze 内容及字节哈希、有效配置与固定重复种子、config/data 哈希、started 与 result 一致性、源码哈希清单及完整 source_snapshot。

静态输入与对应冻结 commit 的实例 JSON 相同。SMT 的场景、窗口、受控设备及数据哈希与固定配置和 source_data 清单一致。144 条原静态记录各有 31 个执行源码快照文件；36 条原 SMT 记录各有 45 个；恢复记录有完整 76 个冻结文件快照，共检查 6,160 个运行时快照文件。

恢复记录另核对原失败 call_id、original_link、原失败证据文件哈希、原样输入、只改变显式 grant 的模型配置、原始 CLI binary SHA，以及 claim/result 的冻结关联。恢复 manifest 的 `original_results_sha256` 与全部 180 条原始 result.json 当前字节哈希完全一致。

四份原始最终回放 JSON 均由已提交的恢复 manifest 单独 SHA 绑定；本次同时验证它们当前文件与恢复 commit 中的 Git 内容。它们按协议保留在线下，**不属于**恢复运行的 76 文件 runtime source_snapshot；本检查没有将未复制审计摘要误判为缺少源码。

## 实际验证与范围

脚本实际执行成功，180/180 原始版本绑定通过，恢复 1/1 通过，错误列表为空。Python 进程 CPU 约 1.51 秒；真实模型、solver 和仿真调用均为 0，没有 Git 提交。

原始结果状态仍为 179 成功、1 失败，失败是 `mk08_B_r1`。本检查没有回写原失败，也没有把恢复结果计入原始首次成功率。它证明版本与字节证据链一致；排程可行性、事件约束和成本恢复审计沿用已经单独执行并绑定的审计，不将本次版本检查扩称为一次新的性能或可行性实验。
