# 本地归档工具

这些脚本只捕获、脱敏、打包和核验已有文件，不运行任何实验或模型，也不执行历史证据代码。Python 3 标准库即可构建；核验既有项目说明 PDF 的文字还需要 `pdftotext`。

1. `archive_stage.py capture --output "$ARCHIVE_DIR" --s1 "$S1_DIR" --claude "$CLAUDE_PROJECT_DIR" --codex "$PERSONAL_CODEX_DIR" --redactions-from-task "$PRIVATE_TASK_FILE"`：清点长度后逐文件捕获；拒绝覆盖已有 snapshot。敏感识别值仅写入私有 redactions.json。
   初次清点之后，运行 `supplement_databases.py capture --output "$ARCHIVE_DIR" --s1 "$S1_DIR"` 补捕获两份科学 SQLite 与 pytest 配置，并记录独立时间。
2. `archive_stage.py build --output "$ARCHIVE_DIR"`：仅读取固定快照。两个本地进程处理文本，队列限制为三项；原始字节和公开字节分别打包。可复用私有目录内按来源 SHA-256 和缓存 SHA-256 双重校验的 public-cache；缓存不是证据来源。
   随后运行 `supplement_databases.py build --output "$ARCHIVE_DIR"`：生成科学 SQLite 的逻辑导出、回导核对，并把原件和公开 SQL 分别合入两层包。
3. `summarize_stage.py --output "$ARCHIVE_DIR"`：从快照导出最终 summary/audit 记录与中文结论，核对冻结 Harness 源码。
4. `finalize_stage.py --output "$ARCHIVE_DIR"`：更新会话工具索引、证据说明、公开及私有 checksum 清单、publication manifest。不会提交或发布。
5. `verify_stage.py --output "$ARCHIVE_DIR"` 与仓库根目录的 `python3 scripts/verify_public_release.py`：检查成员全集、哈希、安全路径、原有文档不变、指标来源与公开泄露模式。完整核验结果先写入仓库外，避免报告哈希自引用。
6. `restore_public.py --archive "$PUBLIC_ARCHIVE" --dest "$NEW_DIRECTORY"`：先逐文件核验再恢复，拒绝覆盖和不安全成员。

Git 中的核验报告对应生成它时的文件集合；报告加入后再次刷新 publication manifest 并复验。清单本身不包含自己的哈希。比较草稿有 11 处既有本机路径；用户要求原字节不变，因此单列为已知复核例外。所有未解释的扫描命中仍导致核验失败。

首次扫描的相对路径和装饰器误报保留在 archive-initial-verification.json。repair_public.py 从不可变原件修复装饰器，验证 30 个 Python 文件除文本常量外的 AST 结构与装饰器均未改变。最终核验可用 --reuse-private-report 引用此前完整私有成员核验；仅在重新核对同一私有包 SHA-256 后复用，默认仍完整读取私有包。
