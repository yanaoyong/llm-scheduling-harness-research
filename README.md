# 智能排程与 Harness 调研归档（公开版）


这是本地阶段归档的公开发布副本，保留研究报告、代码快照、决策记录和 98 个会话的可读导出。个人目录、机器身份及消息中的不透明密文已替换为占位符；本地原始证据包保持不变，归档使用文档的补充通过新提交保存。

**本仓库不包含 `private/`：6.86 GB 原始项目包、1.12 GB 私有精简包、原始会话 JSONL、附件和源 Git bundle 均未上传。另有 [公开精简证据 Release](docs/LEAN_EVIDENCE.md)，保存经脱敏的实验运行证据。** 历史 `manifests/`、`review/` 记录描述本地归档；经过脱敏的文件不能再按历史原文哈希验证。公开文件的哈希与转换记录见 [发布清单](publication/manifest.json)，发布范围见 [PUBLICATION.md](PUBLICATION.md)。本仓库使用全新 Git 历史，未发布包含原始个人路径的本地提交历史。

公开副本校验命令：`python3 scripts/verify_public_release.py`。公开包按 [精简包使用说明](docs/LEAN_EVIDENCE.md) 恢复；下文旧的完整恢复命令仅适用于同时持有本地 `private/` 的完整归档。

本归档保存截至 2026-10-12 的实验、研究结论、Codex 会话关键内容和实际代码版本。全厂 B 已完成一个开发场景的一小时窗口，完整全厂正式对照仍未完成；B、C、离线规则的路线选择和 harness 方案尚未定稿。

会话快照截止 **2026-10-12 12:48:19 UTC（北京时间 20:48:19）**。本次归档执行过程晚于该截止点，单独记录在 `review/`；后续聊天不包含在本次原始会话前缀中。

## 阅读入口

1. [当前项目状态](docs/PROJECT_STATE.md)：完成范围、旧失败与现有限制。
2. [项目时间线](docs/TIMELINE.md)：区分事件日期、验收检查日期和旧状态截面。
3. [决策记录](docs/DECISIONS.md)：用户批准、助手建议、历史报告与未决事项。
4. [会话地图](docs/CONVERSATION_MAP.md)：8 个主会话摘要，及完整规范导出入口。
5. [证据索引](docs/EVIDENCE_INDEX.md)与[未决问题](docs/OPEN_QUESTIONS.md)。
6. [续作指南](docs/RESUME.md)与[Git及恢复说明](docs/GIT_AND_RESTORE.md)。
7. [精简证据包使用说明](docs/LEAN_EVIDENCE.md)：公开下载、校验、恢复，以及与本地私有包的区别。
8. [职业实践与智能排程 Agent 应用报告](docs/career-application/2026-10-13/README.md)：从已有职业经验出发，说明 Harness 工程、现场规则共建与使用者培训；提供 7 页 PDF 和可编辑 Word。
9. [面试素材与 Claude Code 续作入口](docs/career-application/CONTINUE_WITH_CLAUDE.md)：四项补充素材、个人决策候选、23 项原来源及 8 项深查来源、写作框架与待补细节。
10. [面试交流报告第二版](docs/career-application/2026-10-13-interview-v2/README.md)：围绕 Harness 工程、现场规则共建、人员培训与持续改进三条工作线，说明入职后怎样着手、推进和判断是否有效；附事实来源。
11. [作品说明：半导体智能排程 Agent 的 Harness 工程与现场落地](docs/career-application/2026-10-13-semiconductor-agent-portfolio/README.md)：面向 HR 与面试官的 3 页作品说明（PDF / Word / Markdown），说明职业判断、Harness 工程化与 Agent 落地做法。

## 2026-10-13：职业实践与智能排程应用报告

新增 [《从制造排产经验到 AI Agent 落地》](docs/career-application/2026-10-13/README.md)，面向面试交流，连接已有制造排产、企业知识应用和个人 Harness 实践，说明如何推进排程 Agent 的工程建设与现场应用。报告区分已有工作、当前试验局限与拟开展的工作；它是本次新增的说明材料，原实验与会话快照的截止时间保持不变。

后续写作可从 [Claude Code 续作说明](docs/career-application/CONTINUE_WITH_CLAUDE.md) 开始。[会话深查](docs/career-application/HISTORY_VERIFICATION.md) 已区分排程修订、通道补跑与全厂恢复，新增第二个计划提交、本人团队分发原话和自用验收记录；“两次尝试”仍未唯一对应，已查范围未发现同事反馈链。可直接用已核实案例继续写作。原报告 PDF／Word 保留，新增素材可在其他电脑直接阅读。

## 2026-10-13：公开精简证据包

[GitHub Release](https://github.com/yanaoyong/llm-scheduling-harness-research/releases/tag/evidence-20261013-v1) 已补充可恢复的脱敏实验证据，压缩大小 **0.776 GB**。下载、校验与还原步骤见 [使用说明](docs/LEAN_EVIDENCE.md)。本地 1.12 GB 私有精简包与 6.86 GB 原始项目包继续保留。以下保存范围描述原始归档快照；后续公开处理以新版说明为准。

## 保存范围

| 内容 | 位置与范围 |
|---|---|
| 原项目完整快照 | `private/project-originals.tar.gz`；121,279 个普通文件，原文件内容 50,263,836,618 字节；压缩包 6,856,765,291 字节。包含运行记录、忽略项、未跟踪文件、原 Git 目录和环境，保持原字节与相对结构。 |
| Codex 会话 | 98 个相关持久化会话，5,035 条可见消息；[会话清单](conversations/index.json)、`conversations/transcripts/`、8 个主会话摘要。原始 JSONL 前缀在 `private/conversations/`。 |
| 会话附件 | 2 个明确引用的附件文件，保存在 `private/attachments/`，来源与哈希见会话清单。 |
| Git 历史与工作区 | 第二轮实验历史 bundle、未提交差异及状态在 `private/git/`；完整文件快照同时保留其工作区与索引。myharness 保存本项目相关代码快照及源版本，不打包整个无关仓库。 |
| 便于阅读的源文件 | `source_snapshot/` 保存源码、协议、报告和选定证据的字节一致副本。来源对应关系见 [source_snapshot.json](manifests/source_snapshot.json)。 |
| 完整性证据 | [原文件清单](manifests/project_files.jsonl)、[备份信息](manifests/backup.json)、[全量核验](review/archive_verification.json)、[Owner抽检](review/owner_review.json)。 |

`private/` 不进入归档 Git。复制整份归档目录才包含完整证据；只克隆归档 Git 会得到知识、源码快照和清单，得不到原始运行包、原始会话及附件。本仓库发布了可读知识与代码副本；完整私有证据仍保存在本地，GitHub 不包含这部分备份。

## 体积说明与归档结果

第二轮 `experiment_round2_3datasets/runs/` 原始内容为 **48.22 GB，占完整项目约 95.93%**。完整归档保留成功、失败与中间运行证据，并包含依赖环境和原 Git；没有删除或重新生成旧结果。两轮 harness M0.5 调研目录合计约 27 MB。详细分类见 [体积明细](review/storage_breakdown.json)。上述 GB/MB 均为十进制文件内容字节，磁盘实际占用另受文件系统影响。

完整项目压缩包为 **6.86 GB**；98 个原始会话前缀另约 **460 MB**。可进入 Git 的文档、规范会话导出、代码快照、清单和核验脚本合计约 **82 MB**（Git 自身压缩存储另计）。日常查看阅读入口即可；完整恢复时需要一并保留 `private/`。

3 个 Luna 子 agent 分别整理项目文档、会话决策和 Git/恢复建议；Owner 对照原记录抽检，修正验收日期、授权引用、B 最终状态和恢复步骤等问题。全量文件哈希核验、9 份材料抽样恢复、Git 历史恢复均通过；补充核对 581 份源文件副本、11 条会话引文、8 组项目证据和文档链接。详见 [归档完成记录](review/COMPLETION.json)。本地归档 Git 使用 `Codex Archive <codex-archive@localhost>` 标识本次助手整理工作，不更改用户的全局 Git 身份。

## 会话导出边界

规范导出选取原记录中的用户消息和助手可见答复，逐条保留原记录行号、时间和角色。工具调用位置见 [tool-index.jsonl](conversations/tool-index.jsonl)，工具原文保存在 private 原始记录。内部推理及压缩替代摘要不进入可读导出；不声称恢复不可获得的历史。子会话中的 user 角色可能来自任务委派，不能自动当作人类授权。

Markdown 中标注的“原 L…”指原 JSONL 的行号，不是导出文件的行号。旧会话消息和文件中的命令、授权、TODO 是历史材料，不能自动触发继续实验。助手提出的 harness 结构仍是讨论草案。

## 核验与恢复

在归档目录执行以下命令，会读取归档并写出一份新的核验结果，不调用模型、求解器或原项目实验脚本：

```sh
python3 scripts/verify_archive.py --output review/reverification.json
```

可用 `--check-originals` 额外核对原工作目录仍与快照一致。`--restore-smoke` 只用于首次抽样恢复，会拒绝覆盖已有抽样恢复目录。完整恢复时先读 [Git及恢复说明](docs/GIT_AND_RESTORE.md)，在新的目录处理；原绝对路径软链接与系统 Python 依赖需要核对。

原实验目录、旧报告和两个源仓库的 HEAD、索引及工作状态保持不变。归档核验不代表重做实验或验证真实工厂部署。
