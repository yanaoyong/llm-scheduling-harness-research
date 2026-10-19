# 证据范围、哈希与恢复

本次 Git 中保存当前代码、阶段结论、简明记录，以及 [Mac 预检的 28,047 文件可信 SHA-256 清单](TRUSTED_INPUTS.md)。压缩的公开选定证据包已在 Mac 本地归档，计划使用 Release 标签 `evidence-20261019-harness-v6-s0`；公开上传此前被自动审批拦截，尚未发布，下面的 Release 下载命令仅在另行授权并发布后可用。本次清单提交不包含该压缩包。包内 `manifest.json` 逐文件登记原始 SHA-256、公开 SHA-256、大小和是否转换。压缩包哈希见 [构建记录](verification/archive-build.json)，核验结果见 [核验记录](verification/archive-verification.json)。

公开包包含 **2,917** 个文件，展开约 **1.187 GB**，压缩大小 **145,887,459 字节**（约 145.9 MB）。SHA-256：`4b234b48343474b0ca98f98e823e7d472e0d6e982fdcd24f51a922ec257bf8a7`。

## 选定范围

- 所有真实 A/B、smoke、正式中止前缀，包括旧失败、native 请求/响应的公开派生文件、宿主输出、checkpoint/WAL、完整快照和冻结记录。
- 最新修复所需的整状态压力、实际 CycleServer、代理、输出/推理历史测试；复用的固定 pin、额外工具拒绝、请求上限和断网门禁证据。
- 原完整压力的前一版本、原 7 输出离线重放、查询域、A/B 材料、各阶段状态报告与指定验收日志。
- 当前 v6 源文件，以及阶段脚本、登记、排除理由、诊断和历史状态。目录 `goal/` 对应原实验工作目录，`reports/` 和 `logs/` 对应独立环境输出，`source/v6/` 保存冻结源快照。

这不是整个 WORK 的镜像：本机认证、用户配置目录、CLI 状态数据库、原生二进制副本、构建缓存、venv 和所有历史离线矩阵的重复大对象未复制。未入包的原始离线中间产物仍保存在原工作目录。缺少的物理环境与 sealed 输入需按仓库旧证据和 Mac runbook 另行准备；不能声称只克隆本仓库就能重跑真实实验。

## 公开处理和原始记录

遵循仓库 [公开规范](../../../PUBLICATION.md)：个人路径替换为占位符；凭据、cookie、内部推理、不透明密文不发布。保留公开物理事实、最终计划、成功/失败、工具调用和 token 用量。移除内部推理内容不删除 reasoning token 计数。

原始选择集另存本地 `archive/20261019_harness_v6_s0/private/`，含原始字节包及清单；原 WORK 保持不变。原始包不进入 Git。原始哈希、登记中冻结文件哈希、签名链和路径是历史溯源信息，不冒充脱敏文件的现行哈希。公开哈希用于验证发布字节；不要使用已脱敏的旧登记直接启动模型，或把公开派生文件的哈希差异当成原实验篡改。

## 只读核验

在仓库根目录执行：

```sh
gh release download evidence-20261019-harness-v6-s0 \
  --repo yanaoyong/llm-scheduling-harness-research \
  --pattern harness-v6-s0-public.tar.gz --dir downloaded-evidence
python3 docs/updates/2026-10-19/archive_tools/verify_harness_archive.py \
  --archive downloaded-evidence/harness-v6-s0-public.tar.gz
python3 scripts/verify_public_release.py
```

第一个命令检查压缩包哈希、全部成员哈希、安全路径、关键验收结论，并从全部真实 native trace 重新加总 55 次尝试、51 次已知响应、4 次未知用量失败及 token 总数。不会执行历史脚本、模拟器或模型。

如需阅读完整选定证据，先核验，再解压到新的空目录：

```sh
mkdir harness-v6-s0-evidence
tar -xzf downloaded-evidence/harness-v6-s0-public.tar.gz -C harness-v6-s0-evidence
```

历史脚本保留原相对结构与路径占位符，仅供审计和续作；跨机执行需重建环境、重映射路径、校验原始输入并重新登记。此次归档没有进行模型复跑，也没有扩展已暂停实验的授权。
