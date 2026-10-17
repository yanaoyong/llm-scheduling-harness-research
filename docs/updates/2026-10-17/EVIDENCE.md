# 证据包、校验与恢复

这次采用三层保存：Git 中的可读会话、代码和报告增量；配套 Release 中的脱敏科学证据增量；本地完整原始快照。后两层不能混为原始字节一致的同一个包。

## Git 中直接阅读

当前目录 `project/` 保存后续源码、配置、测试与报告的可读增量，`conversations/` 保存后续可见消息和工具位置索引。未变化的旧源码与文档继续在仓库原有 `source_snapshot/`、`conversations/` 等目录。当前目录不是独立可运行的完整工厂环境。

## 公开增量证据包

下载 [evidence-20261017-followup-v1](https://github.com/yanaoyong/llm-scheduling-harness-research/releases/tag/evidence-20261017-followup-v1) 的全部附件。GitHub 自动生成的 Source code ZIP 只包含仓库内容，不包含 Release 证据附件。

分片大小可以不同；按文件名字典序拼接全部 `.part-*` 文件即可。上传过程中把未完成的大分片继续切小，不改变拼接后的完整证据包或其 SHA-256。

```sh
gh release download evidence-20261017-followup-v1 \
  --repo yanaoyong/llm-scheduling-harness-research \
  --dir followup-evidence-20261017
cd followup-evidence-20261017
shasum -a 256 -c checksums.sha256
cat followup-evidence-20261017.cas.tar.zst.part-* > followup-evidence-20261017.cas.tar.zst
shasum -a 256 -c archive-checksum.sha256
python3 followup_archive.py verify \
  --archive followup-evidence-20261017.cas.tar.zst \
  --report verify-local.json
```

需要 Python 3 和 `zstd` 命令。Linux 可用 `sha256sum -c`。校验记录和包大小见 [构建记录](verification/build_result.json)、[包校验](verification/public_package_verification.json)、[脱敏检查](verification/privacy_review.json) 和 [GitHub 附件哈希核验](verification/github_assets.json)。来源与范围见 [选择清单](verification/selection.json)。这些哈希用于核对完整性，不是独立数字签名。

恢复整个增量到尚不存在的目录：

```sh
python3 followup_archive.py restore \
  --archive followup-evidence-20261017.cas.tar.zst \
  --dest restored-followup \
  --report restore-local.json
```

也可加 `--prefix project/experiments/context_window_batch60_20261016/live_pilots/extended_three_group_deadline_completion_20261017/` 只恢复最后一段。工具核对所有包内对象后再恢复选定文件，保留普通文件的字节、权限及纳秒修改时间；拒绝覆盖已有目标，不执行历史脚本、不调用模型、不导入 SQL、不创建原绝对路径软链接、不应用删除清单。

这是相对于 2026-10-12 原始快照的增量。需要更早证据时另取 [2026-10-13 公开精简包](../../LEAN_EVIDENCE.md)，在新目录中分别恢复并按路径阅读；不要覆盖原实验目录。未修改的旧文件不重复发布，旧包本来未公开的私有材料不会因本次增量变成公开可用。

## 压缩对象与数据库

- Harness 的 `.z` 对象经过解压、脱敏并以 zlib 重压缩，公开路径追加 `.public.json.z`。可以用 `zlib.decompress(Path(path).read_bytes()).decode('utf-8')` 阅读；部分内容是普通 UTF-8 文本而非 JSON。包内清单登记压缩文件和解压内容各自的 SHA-256。
- 原文件名中的对象引用用于历史溯源，不能拿来验证脱敏后的公开内容。`transformations.jsonl` 记录原始哈希和公开哈希；公开版没有重新签署旧账本。
- 科学 SQLite 从完整快照中的独立副本导出，存在 WAL 时使用一同捕获的副本。`.public.sql` 保留 schema 和脱敏后的行值，经过临时导入、完整性、逐表行数和行值核对。工具不会自动执行 SQL。
- Codex 运行状态数据库、运行守卫、原始会话、凭据、环境缓存、二进制附件与源 Git 元数据不公开。具体路径与排除原因在包内 `excluded.jsonl`。缺失的第三方二进制按已有来源与许可另行获取。

## 本地完整原件

项目内 `archive/20261017_followup_archive/private/` 保存完整项目 CAS 包、逐路径清单、73 份原始会话前缀、3 份明确引用的附件、原 B 的 Git bundle 及未提交/索引差异。约 57.28 GB 逻辑原文件压缩为 5.84 GB，原始会话和 Git 备份另计。它们没有上传 GitHub，也没有删除旧完整包。

公开的 [原始快照核验记录](verification/snapshot_result.json) 和 [全部原始对象核验](verification/private_object_verification.json) 供索引；拥有本地私有包时，可用同一 `followup_archive.py verify` 检查其对象。完整私有恢复需要足够空间保存展开文件与临时对象；建议至少 110 GB 空闲，或用前缀选择少量文件。恢复工具只物化普通文件，原软链接目标保存在私有清单中，需单独审阅。

原始字节、完整签名链或未脱敏历史需要本地私有原件。本次公开归档校验不代表重新运行模型、重新仿真或证明真实工厂收益。
