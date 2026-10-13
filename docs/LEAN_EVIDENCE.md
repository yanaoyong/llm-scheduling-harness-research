# 精简证据包：下载、使用与恢复

更新于 2026-10-13。[下载公开精简包](https://github.com/yanaoyong/llm-scheduling-harness-research/releases/tag/evidence-20261013-v1)。大文件通过 GitHub Release 发布；Git 仓库保存使用文档、恢复工具和验收摘要。

| 版本 | 压缩大小（十进制） | 用途与边界 |
|---|---:|---|
| 公开精简版 | 776,111,570 字节（0.776 GB） | 脱敏后的实验与研究证据，可公开分享；SQLite 为逻辑 SQL 导出 |
| 本地私有精简版 | 1,121,155,426 字节（1.121 GB） | 保留未脱敏原文、原始会话前缀、附件、科学 SQLite 和已有 Git 备份；未上传 |
| 原始项目完整包 | 6,856,765,291 字节（6.857 GB） | 恢复原应用状态、环境、原 Git 工作元数据等；完整归档另有会话与 Git 备份；未上传 |

公开版恢复 94,733 个文件，逻辑内容 38.58 GB，按 SHA-256 去重为 58,656 个对象。全量还原、重新计算全部文件哈希、权限与修改时间检查已通过；38 份 SQLite 逻辑导出也完成临时导入与行值对照。隐私检查包含解码后的 SQLite BLOB；自动扫描与抽检不等于绝对隐私保证。

公开压缩包 SHA-256：`32f0c84b1f4e79d98d9b3ff3dfbc4f35200ab4e59d28a88d358cbaa3190b40bd`。

此页是后续发布说明；不会改变 2026-10-12 冻结的实验结果、会话截止点、历史报告或原始签署。公开包的 `archive/` 目录冻结于旧公开提交 `d9605ee`，本页为随后新增入口；当前说明以仓库为准。


本包于 2026-10-13 从本地“必要证据＋去重存储”精简版派生，供公开阅读、追溯和离线检查。发布位置为 [GitHub Release evidence-20261013-v1](https://github.com/yanaoyong/llm-scheduling-harness-research/releases/tag/evidence-20261013-v1)。它是**脱敏后的公开副本**；本地 1.12 GB 私有精简包和 6.86 GB 原始项目包继续保留，不被替换。

## 下载与依赖

在 Release 的 Assets 下载全部附件。GitHub 自动生成的 `Source code.zip` / `tar.gz` 只有仓库文档和源码，不包含大证据包。也可以使用 GitHub CLI：

```sh
gh release download evidence-20261013-v1 \
  --repo yanaoyong/llm-scheduling-harness-research \
  --dir evidence-20261013
cd evidence-20261013
```

需要 Python 3.9+ 和 `zstd` 命令。macOS 可用 `brew install zstd`；其他系统安装 Zstandard 命令行工具。使用工具不需要模型账户或 API key。`evidence_store.py` 与包放在同一个目录即可。

## 校验、还原与阅读

先核对 Release 附件，再核对包内每个内容对象：

```sh
shasum -a 256 -c checksums.sha256
python3 evidence_store.py verify --report verify-local.json
```

Linux 也可用 `sha256sum -c checksums.sha256`。若压缩包同目录的 `build_result.json` 存在且登记的包名匹配，`verify` 会核对其中的整体 SHA-256；否则需通过 `--expected-sha256 <可信清单中的包SHA256>` 指定。工具始终验证每个对象与包内清单是否匹配，但不会认证清单来源。先从可信仓库获取校验记录；同来源的校验和用于发现传输损坏，不是独立数字签名。

还原目录必须不存在，建议预留至少 45 GB 空间（具体展开字节数见 `selection.json`，文件系统开销另计）：

```sh
python3 evidence_store.py restore \
  --dest ./restored-public-evidence \
  --report restore-local.json
```

还原过程会逐文件重新计算 SHA-256，并核验记录的权限、修改时间与包内可移植软链接；恢复文件相互独立，不用硬链接。原内部绝对软链接改成指向还原树的相对链接。建议使用支持 POSIX 权限、软链接和纳秒修改时间的文件系统；未在 Windows 文件系统上验证。

- `restored-public-evidence/project/`：两轮排程实验、输入/配置、代码、检查点、轨迹、成本与调用记录、失败/重试/恢复证据、M0.5 调研。
- `restored-public-evidence/archive/`：已公开且经过脱敏的归档知识、源码快照和 98 个会话的可见消息导出。此目录冻结于 `selection.json` 记录的公开仓库提交；最新版使用文档以 GitHub 仓库为准。
- `restored-public-evidence/_lean_store/`：本次公开包的清单、排除原因、转换映射、覆盖与检查记录。

日常先看 `archive/docs/PROJECT_STATE.md`、`DECISIONS.md`、`EVIDENCE_INDEX.md` 和 `CONVERSATION_MAP.md`，再沿索引查原实验文件。`selection.json` 给出文件数和体积；`inventory.jsonl` 连接“逻辑路径 → 公开 SHA-256”；`transformations.jsonl` 连接原始哈希与公开哈希；`excluded.jsonl` 区分私有精简版已有排除和本次公开处理。原 `archive/` 材料由已公开归档替换，也记录为替换原因，不意味着对应知识文档缺失。

若只想做完整还原验证，不保留展开结果：

```sh
python3 evidence_store.py restore-check --report restore-check-local.json
```

该命令完整展开后再次核验，最后仅删除自己创建的临时目录；也需要充足临时磁盘空间。解压 Zstandard/TAR 只会得到内容寻址的 `objects/<sha256>`，要恢复可读的原目录结构请使用上述工具。

## 公开处理与数据库

保留科学文本证据，包括 UTF-8 的 `.bin` 原始采集副本；76 份带 BOM 的官方 UTF-16 原始输入经解码检查后保持原字节，见 `utf16_input_review.json`。没有按成功/失败筛选实验。个人主目录、机器身份、临时个人目录、联系邮箱和不透明密文被替换；原始私有 Codex rollout、会话附件、源 Git 历史及个人初始附件不发布。编译缓存、编译产物、上游模型权重与 W&B 追踪状态、第三方 ZIP/PDF/图片/字体等不在此公开包中；已有来源 URL、版本、哈希和许可文本保留，缺失资源沿来源记录获取。本包不另行赋予第三方材料统一许可证。

38 个科学 SQLite 按原路径派生为 `原文件名.public.sql`。这是包含表结构、记录值和 BLOB 的逻辑导出，BLOB 解码后也进行脱敏检查；未直接发布数据库二进制。`sqlite_exports.json` 提供原路径到导出路径的映射，`sqlite_verification.json` 记录临时导入后的数据库完整性、schema，以及按表比较脱敏后行值的多重集（不验证存储行顺序，序号列仍参与比较）。原数据库文件布局、页内容、WAL、原始字节哈希不会由逻辑导出恢复。

需要查询时，另安装 `sqlite3` 命令，可在新的独立文件中手动导入某份已经校验的 SQL，例如：

```sh
sqlite3 ./new-ledger.sqlite3 < ./restored-public-evidence/project/某目录/ledger.sqlite3.public.sql
```

将示例 SQL 路径改为实际路径，`new-ledger.sqlite3` 应为尚不存在的文件。还原工具不会自动导入 SQL 或执行历史实验脚本。

## 结论边界与证据等级

本包基于公开 SMT2020/FJSP 仿真基准，不证明真实工厂上线效果；B、C 和离线规则的最终公平对照仍未完成。公开脱敏会改变文件字节；历史报告中的原文哈希、账本链、签署和绝对路径仍指向私有原始证据，不能拿它们来证明公开文件逐字相同。转换后没有重新签署账本，也没有把失败改成成功。

公开校验通过只说明发布包完整、可按其公开清单恢复；不等于重新运行模型、求解器、仿真或历史审计。需要原始哈希链取证、完整原始会话、附件或源 Git 历史时，使用本地私有精简包；需要被剔除的应用状态、环境或完整 Git 工作元数据时，使用原始完整归档。

## 本地私有精简版的使用

在项目根目录进入 `archive/20261013_lean_evidence/`，执行：

```sh
shasum -a 256 -c checksums.sha256
python3 evidence_store.py verify --report verify-again.json
python3 evidence_store.py restore --dest /path/to/new-private-restoration --report restore-private.json
```

该目录的工具默认读取 `evidence.cas.tar.zst`，公开版工具默认读取 `public-evidence.cas.tar.zst`；不要混用脚本、包与校验清单。私有版展开约 39.44 GB，恢复目录必须不存在。制作结果见该目录的 `RESULTS.md`、`verification.json` 和 `final_review.json`。原始完整包仍位于 `archive/20261012_project_archive/private/project-originals.tar.gz`，恢复顺序参见 [Git及恢复说明](GIT_AND_RESTORE.md)。这些本地文件没有随 GitHub Release 上传。
