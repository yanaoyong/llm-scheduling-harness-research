# 本次归档实现

这些脚本记录本次捕获、公开派生、压缩对象补充处理、会话导出和打包过程，供审阅转换逻辑。它们依赖原本地目录布局、固定截止点及私有快照；不要在公开仓库中直接执行捕获或发布脚本。

日常读取只使用仓库 `scripts/followup_archive.py` 或 Release 同名工具的 `verify` / `restore` 命令。该工具不执行实验、不联网、不导入 SQL，恢复目标必须不存在。

顺序为 capture_followup → build_public_followup → complete_public_objects → pack_public_followup；会话与阅读文档由两个 build/write 脚本生成。最初公开文本筛选不能读取 Harness 压缩对象，后续明确解压、脱敏、重压缩并覆盖选择清单；最终选择清单与核验报告描述完成后的范围。过程中的原始证据与失败没有改写。
