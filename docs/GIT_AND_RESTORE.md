# 本地 Git 与恢复说明

**2026-10-13 补充：**[精简证据包使用说明](LEAN_EVIDENCE.md) 提供公开 Release 的下载、校验、目录还原、SQLite 查询与私有版边界。下文保留原始归档的历史说明。

本说明对应本地归档 `archive/20261012_project_archive/`。归档 Git 只保存可审阅的知识文档、已授权可读的会话对话、必要源码快照和清单/脚本。完整会话原文、附件/大型证据包、源仓库 Git bundle、dirty/untracked 文件副本及 diff 属于本地 private 数据，必须受归档 `.gitignore` 约束，不提交、不推送。归档与源目录位于同一磁盘，同盘副本不构成异地备份。

## 源仓库状态与边界

只读检查发现 `experiment_round2_3datasets/` 的 HEAD 与 index 不应被改写；检查时工作树有 4 个 tracked modified 文件、220 个 untracked 项，`git diff --stat` 为 4,184 行新增、22 行删除。忽略规则统计到 642 个 ignored 项。`runs/` 约 47 GiB，整个第二轮源目录约 48 GiB。未跟踪诊断资料、忽略的运行和大证据、正式配置与账本都需要纳入 private 完整文件副本；bundle 只保存 Git 提交历史，不能保存当前 dirty/untracked 状态。对 dirty 状态另存原始文件副本和 `git diff --binary`，保留相对路径、文件类型及校验清单。

`__LOCAL_HOME__/Downloads/大模型训练营/myharness` 检查时有 2 个 tracked modified 文件、约 112 个 untracked 项（status 汇总约 114 行），Git pack 约 43.59 MiB。它是个人通用 harness 仓库，不能整体收入本项目归档。仅按本项目运行记录、绑定文件和源快照实际引用的代码路径挑选最小依赖快照，并记录源仓库 HEAD、路径、文件哈希及本项目绑定关系；不要纳入个人配置、`.claude`、无关报告或其他项目。

第二轮存在指向源项目绝对路径的冻结 `runs/`、`progress/` 软链接，以及 `.venv` 指向 `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12` 的软链接。打包时默认不跟随链接；逐个记录链接原文、目标存在性和用途。需要保存的实验状态文件应通过清单指定复制其实际内容，同时保存链接映射。恢复到另一目录后，原绝对链接不会自动生效；不要将恢复动作解释为完整复现环境。

`experiment_round2_3datasets/README.md`、`progress/evidence-manifest.json` 与相关 history-integrity 清单要求保留完整日志和大型证据；README 明确说模型输出不能重生成、旧的 replay/audit 签署与绑定文件不能覆盖，重跑 README 核验需使用独立输出路径。恢复后任何可能刷新时间戳、重写签署、改写输入哈希或发起模型/solver 任务的脚本都不得自动运行。先验证归档副本哈希，再做只读审查。模型配额、外部服务可用性、账户权限和原对话附件访问授权不会随文件副本或 Git bundle 自动恢复。

## 恢复顺序

1. 将归档副本复制到独立恢复目录；先核验 `manifests/` 中的文件清单与哈希、私有副本清单、bundle 文件哈希和 bundle 可列出的 refs。不要覆盖现有源目录。
2. 首选在空的恢复目录还原 `private/project-originals.tar.gz`，其中包含第二轮实验的原 `.git`、索引与实际工作树，随后按清单核验。`private/git/experiment_round2_3datasets/history.bundle` 可在另一个空目录恢复提交历史，但单独克隆 bundle 不包含未提交、未跟踪和忽略项。两个 patch 是取证材料，不要把相对 HEAD 的完整 worktree patch 与 index patch 连续应用而重复变更。恢复前后均保存清单，不对原仓库执行 checkout/reset/clean 或 index 刷新。
3. 依清单恢复大型私有证据及会话附件到相对路径；对缺失附件/外部引用标记不可用，不从互联网猜补。检查符号链接清单，只在理解用途后重建为相对链接或继续使用副本路径。
4. 先只读检查 README、协议、输入绑定、manifest、接受结果和 QA 记录。可用归档提供的 `scripts/verify_archive.py` 校验文件完整性；此校验不得执行项目脚本、模型请求、solver、安装或产出重生成。
5. 只有明确需要时，才在新的隔离副本里制定逐项复现方案；不重跑模型/solver，不覆写历史签署或受哈希绑定文件。复现输出使用新的路径和新版本号，并把环境/依赖/权限差异单独记录。

绝对路径、失效软链接、外部二进制、系统 Python、外部模型端点、秘密凭据及会话附件权限均需人工核对。归档中不得存 API token、`.env` 或 keychain 内容。

## 验收门槛

参见 [`../review/git_review.json`](../review/git_review.json)。在 archive Git 首次提交之前，需确认 private 路径确实被忽略，且大证据、原始会话与 bundle 不在暂存区；脚本应核验 bundle 与完整文件备份两条恢复路径，并且对软链接使用不会意外追随的复制规则。最终验收需证明源仓库 HEAD/index/工作树在归档过程中保持不变；这项状态检查应由归档 Owner 在其备份操作前后留证。
