#!/usr/bin/env python3
"""Finalize local documentation and publication hashes; never commits or publishes."""
import argparse, json, subprocess
from pathlib import Path
from archive_stage import ROOT, DEST, save, sha, export_session

def main(output):
 build=json.loads((DEST/'verification/archive-build.json').read_text());capture=json.loads((output/'private/capture.json').read_text());release=output/'release'
 public_capture=json.loads((DEST/'verification/capture.json').read_text());public_capture['evidence_snapshot_cutoff_utc']=capture.get('primary_inventory_cutoff_utc',capture['cutoff_utc']);public_capture['supplement_capture_utc']=capture['cutoff_utc'];public_capture['growing_prefixes']=[e['path'] for e in capture['files'] if e['source_changed_after_inventory']];save(DEST/'verification/capture.json',public_capture)
 # Keep the 10-17 tool-index convention: bodies remain in private prefixes.
 rows=[export_session((output/'private/snapshot'/s['path']).read_bytes(),s,capture['cutoff_utc']) for s in capture['sessions']]
 index=json.loads((DEST/'conversations/index.json').read_text());index['sessions']=rows;index['archive_cutoff_utc']=capture['cutoff_utc'];save(DEST/'conversations/index.json',index)
 conversation_readme=DEST/'conversations/README.md';conversation_text=conversation_readme.read_text().replace('| codex /','| codex-main /')
 role_note='记录中的 user 是消息角色；子会话或命令执行会话中的消息可能来自委派者，不能直接视为人类授权。'
 if role_note not in conversation_text:conversation_text+='\n'+role_note+'\n'
 conversation_readme.write_text(conversation_text)
 body=f'''# 证据范围、哈希与恢复

公开证据包发布于 Release `evidence-20261020-harness-v6-s1`（https://github.com/yanaoyong/llm-scheduling-harness-research/releases/tag/evidence-20261020-harness-v6-s1），下载后按下文 checksums.sha256 校验。

## 三层内容

- Git：中文阶段结论、会话 Markdown/JSONL/工具索引、原有比较草稿与项目说明链接、小型阶段记录、源码哈希和归档工具。
- 待发布附件：`harness-v6-s1-public.tar.gz`，{build['files']:,} 个科学证据文件，展开 {build['logical_bytes']:,} 字节，压缩 {build['archive_bytes']:,} 字节。配套 `manifest.json`、`archive-build.json`、`checksums.sha256`。尚未发布，不提供虚构下载链接。
- 本地私有：仓库外 `20261020_harness_v6_s1/private/` 中的原始字节包、逐文件清单、捕获记录和构建快照。原始包 {build['private_files']:,} 文件、压缩 {build['private_bytes']:,} 字节。包含会话原件、内部内容和 tool-results spill，绝不进入 Git 或公开附件。

公开压缩包 SHA-256：`{build['archive_sha256']}`。

私有原始压缩包 SHA-256：`{build['private_sha256']}`。

科学运行证据与会话的首轮快照截止 UTC {capture.get('primary_inventory_cutoff_utc',capture['cutoff_utc'])}；两份既有科学数据库及 pytest 配置的补捕获截止 UTC {capture['cutoff_utc']}，北京时间 {capture['cutoff_beijing']}。补捕获未纳入首轮之后的新实验结果。按清点时长度读取，不是原子文件系统快照。当前 Claude/Codex 会话及仍增长的 audit-opt 记录是前缀；源文件增长情况在私有 capture.json，完成时间与语义在 [公开捕获记录](verification/capture.json)。

## 选择与脱敏

科学包保留整个 S1 树中可公开的文本证据：任务、V/W 阶段报告、最终/历史登记、失败日志、smoke/formal、checkpoint、完整物理轨迹与快照、native 请求输出、离线参考、恢复资格与 audit-opt 候选/旧版/测量。实验专用 home 中的文本 rollout 属科学证据，不作为开发对话。所有普通文件及软链接的排除逐项登记于 [excluded.jsonl](evidence/excluded.jsonl)，包内有同名副本；不跟随软链接，不读取凭据，不复制 CLI 数据库、二进制或缓存。两份科学 SQLite（G0 与 contexts）例外保留原件于私有包，公开 .public.sql 逻辑导出已回导核对完整性、逐表行数及全部脱敏行值，见 verification/sqlite-exports.json。

复用 10-17 脱敏政策和 10-19 线性邮箱处理，额外移除 Claude 私有内容与签名，图片全部替换为占位符；邮箱、指定个人标识、本机路径和主机名不公开。工具索引保留原行号及内容哈希，正文仍在私有前缀，spill 文件列在会话索引。未经脱敏的签名链与冻结哈希仅为历史原始字节引用；公开内容以 manifest 中的 sha256 校验，不能将脱敏哈希差异解释为原实验篡改。

[源码比对](verification/source-comparison.json) 核对捕获源码与已有 Git 目录及最终两份 amendment：全部相同，因此 source.diff 为空；完整源码另包含于公开包 source/v6。阶段驱动、优化候选及其历史 diff 位于 s1 子树。冻结登记引用的外部 physical 输入、官方二进制、模型目录等未完整打包；恢复是证据阅读恢复，不承诺仅凭本包即可运行实验。既有源码和本包均未执行。

## 只读核验及恢复

在仓库根目录，设置 ARCHIVE_DIR 为仓库外 `20261020_harness_v6_s1` 目录；它含 release/ 与 private/。完整核验需要私有包持有人权限：

```sh
python3 -B docs/updates/2026-10-20/archive_tools/verify_stage.py --output "$ARCHIVE_DIR"
python3 scripts/verify_public_release.py
(cd "$ARCHIVE_DIR/release" && sha256sum -c checksums.sha256)
```

核验器逐文件检查公开/私有包成员清单、SHA-256、安全路径、Git 清单、原有文档未变、报告数值来源，并扫描公开包与本次 Git 改动。原始 private 包没有被当作公开扫描输入。记录见 [最终归档核验](verification/archive-verification.json)、[发布清单核验](verification/publication-verification.json) 和 [Python 装饰器保留检查](verification/decorator-preservation.json)。自动扫描覆盖所列模式，不等于识别全部可能个人信息。比较草稿原文有 11 处本机绝对路径；因用户明确要求原字节不变，保留并作为核验报告中的复核例外，不冒充路径扫描零命中。

只有公开附件时，先校验 checksums.sha256，再检查包内 manifest。以下命令只在新空目录中恢复公开普通文件，不运行任何历史代码：

```sh
python3 -B docs/updates/2026-10-20/archive_tools/restore_public.py --archive "$ARCHIVE_DIR/release/harness-v6-s1-public.tar.gz" --dest "$ARCHIVE_DIR/restored-s1"
```

科学数据库保存为 SQL，不是原 SQLite 文件字节。需要查询时，可用 SQLite 在新空数据库中导入对应 .public.sql；不要覆盖原库。SQL 回导已在构建时经过行值核验，公开原始哈希仍仅指向私有源库。

恢复器先核对包内每个文件，拒绝软链接、绝对路径、重复成员及路径穿越，并拒绝已存在的目标。若需重新生成此归档，archive_stage.py 的 capture 接受显式 --s1、--claude、--codex、--output 路径；build 仅从不可变 private/snapshot 派生，再按 archive_tools/README.md 完成科学数据库补捕获及逻辑导出，运行 summarize_stage.py、finalize_stage.py 和 verify_stage.py。新的 capture 会有新的截止点，不能冒充本次字节。
'''
 (DEST/'EVIDENCE.md').write_text(body)
 for name in ('manifest.json','archive-build.json'):
  assert (release/name).exists()
 (release/'checksums.sha256').write_text(''.join(sha((release/n).read_bytes())+'  '+n+'\n' for n in ('harness-v6-s1-public.tar.gz','manifest.json','archive-build.json')))
 (output/'private/checksums.sha256').write_text(''.join(sha((output/'private'/n).read_bytes())+'  '+n+'\n' for n in ('harness-v6-s1-original-selected.tar.gz','manifest.json','capture.json','capture-primary.json','redactions.json')))
 # Preserve old provenance metadata; update current-byte hashes and append new paths.
 path=ROOT/'publication/manifest.json';manifest=json.loads(path.read_text());old={e['path']:e for e in manifest['files']}
 files=set(old)
 for cmd in (['git','diff','--name-only','-z'],['git','ls-files','--others','--exclude-standard','-z']):files.update(x for x in subprocess.check_output(cmd,cwd=ROOT).decode().split('\0') if x)
 files.discard('publication/manifest.json')
 for name in sorted(files):
  p=ROOT/name
  if not p.is_file():continue
  raw=p.read_bytes();row=old.setdefault(name,{'path':name,'source_tracked_sha256':None});row.update({'public_sha256':sha(raw),'bytes':len(raw)})
 manifest['files']=[old[n] for n in sorted(old)];manifest['public_file_count_excluding_this_manifest']=len(old)
 manifest['archive_20261020']={'cutoff_utc':capture['cutoff_utc'],'evidence_snapshot_cutoff_utc':capture.get('primary_inventory_cutoff_utc',capture['cutoff_utc']),'conversation_cutoff_utc':capture.get('conversation_cutoff_utc',capture['cutoff_utc']),'release_status':'published','public_asset_sha256':build['archive_sha256'],'model_calls':0}
 save(path,manifest)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);main(p.parse_args().output)
