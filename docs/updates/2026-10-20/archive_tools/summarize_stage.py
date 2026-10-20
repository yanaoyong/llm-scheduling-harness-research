#!/usr/bin/env python3
"""Derive readable facts from the immutable private capture, without rerunning audits."""
import argparse, difflib, json, datetime as dt
from pathlib import Path
from archive_stage import ROOT, DEST, sha, save, transform, text

def display(value):
 return f'{value:,.3f}'.rstrip('0').rstrip('.') if isinstance(value,float) else f'{value:,}'

def main(output):
 snap=output/'private/snapshot';capture=json.loads((output/'private/capture.json').read_text());runs=[]
 primary=capture.get('primary_inventory_cutoff_utc',capture['cutoff_utc']);primary_beijing=dt.datetime.fromisoformat(primary).astimezone(dt.timezone(dt.timedelta(hours=8))).isoformat()
 paths=sorted(snap.glob('s1/goal/formal-*-s1/summary.json'))+sorted(snap.glob('s1/stage-s1/w5/formal-S1-*/summary.json'))
 for path in paths:
  relative=path.relative_to(snap);audit=path.parent.parent/(path.parent.name+'-audit.json');s=json.loads(path.read_text());a=json.loads(audit.read_text())
  for p in (path,audit):
   raw,reason=transform(p.read_bytes());assert reason is None;dest=DEST/'evidence/records'/p.relative_to(snap);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
  runs.append({'name':path.parent.name,'summary_path':relative.as_posix(),'audit_path':audit.relative_to(snap).as_posix(),'start':s['start'],'end':s['end'],'stop_reason':s['stop_reason'],'audit_passed':a['passed'],'evidence_audit_passed':a['evidence_audit_passed'],'gate_errors':a['gate_errors'],'totals':s['totals']})
 comparisons=[]
 for p in sorted(snap.glob('s1/audit-opt/results/**/comparison.json')):
  d=json.loads(p.read_text());comparisons.append({'path':p.relative_to(snap).as_posix(),'identical':d.get('identical'),'available':d.get('available',True)})
 parameters={arm:{k:json.loads((snap/('s1/stage-s1/w5/registration-formal-S1-'+arm+'.json')).read_text())[k] for k in ('delta_seconds','delta_min_seconds','horizon_seconds','trajectory_seeds')} for arm in ('d300','d900')}
 save(DEST/'evidence/summary.json',{'S1_parameters':parameters,'scope':'S0-style short window (directory goal, historical suffix s1) and S1 one-hour W5 arms','model':'gpt-6.1-sol','runs':runs,'audit_optimization_comparisons_at_cutoff':comparisons,'audit_optimization_final_report_present':(snap/'s1/audit-opt/REPORT.md').exists(),'model_calls_during_archive':0})
 # The frozen source root is the existing Git snapshot; prove equality at capture.
 source=[]
 for e in capture['files']:
  if e['path'].startswith('source/v6/'):
   rel=e['path'][len('source/v6/'):];p=ROOT/'docs/updates/2026-10-17/project/experiments/harness_v6_20261017'/rel
   source.append({'path':rel,'captured_sha256':e['sha256'],'existing_git_sha256':sha(p.read_bytes()),'identical':e['sha256']==sha(p.read_bytes())})
 frozen=[]
 for name in ('s1/goal/technical-amendment-s1-v2.json','s1/stage-s1/w5/technical-amendment-stage-s1.json'):
  d=json.loads((snap/name).read_text())
  for path,h in d['frozen_files'].items():
   if 'harness_v6_20261017/' in path:
    rel=path.split('harness_v6_20261017/',1)[1];actual=sha((snap/'source/v6'/rel).read_bytes());frozen.append({'amendment':name,'path':rel,'frozen_sha256':h,'captured_sha256':actual,'identical':h==actual})
 assert all(x['identical'] for x in source+frozen)
 save(DEST/'verification/source-comparison.json',{'existing_git_source':'docs/updates/2026-10-17/project/experiments/harness_v6_20261017','changed_source_files':0,'source':source,'frozen_source_checks':frozen,'diff':'empty: all captured source files equal the existing Git snapshot, and all amendment-frozen harness source hashes match'})
 (DEST/'verification/source.diff').write_text('')
 lines=['# Harness v6：S0 后续与 S1 阶段归档（2026-10-20）','','**S0 短窗口保留 E1/P2 各三次正式尝试，其中五次到达终点；S1 的 Δ=300 与 Δ=900 各一条一小时轨迹通过最终审计。** E1 第三次提前失败，不能把 3+3 次尝试写成六条成功轨迹。','','先看 [机器可读结果](evidence/summary.json)、[证据与恢复](EVIDENCE.md) 和 [会话索引](conversations/README.md)。原有 [比较草稿](COMPARISON_DRAFT.md) 与 [半导体 Agent 作品材料新版](../../career-application/2026-10-20-semiconductor-agent-portfolio/) 保持原字节，旧版不改。','',f'科学运行证据与会话的首轮快照截止 UTC **{primary}**，北京时间 **{primary_beijing}**。文件按清点时长度截取，读取在随后完成，不声称原子快照；正在写入的 Claude 主会话及本次 Codex 会话仅保存前缀。','',f'另于 UTC {capture["cutoff_utc"]}（北京时间 {capture["cutoff_beijing"]}）补捕获两份既有科学 SQLite 与 pytest 配置。补捕获经过单独记录，未重新捕获会话或后续实验结果。', '', '## S0 短窗口：3+3 次正式尝试','','这里沿用比较草稿的 S0 阶段称呼；来源目录是 `s1/goal/`，文件名带 `-s1`，表示切换官方 Codex/sol 后的实现版本。窗口为 702→1603.1 秒。以下逐行来自各运行 `summary.json` 与对应 `*-audit.json`，均可由机器可读结果定位。','','| 尝试 | 会话 / 请求 | input / cached / output | 终点 | 正式审计 |','|---|---:|---:|---:|---|']
 for r in runs[:6]:
  t=r['totals'];lines.append(f'| {r["name"]} | {t["sessions"]} / {t["requests"]} | {t["input_tokens"]:,} / {t["cached_tokens"]:,} / {t["output_tokens"]:,} | {r["end"]} | {"PASS" if r["audit_passed"] else "未到登记终点"} |')
 lines += ['','E1 seed 3 两次提交均被拒绝（资格约束、机器队序），以 consecutive_failures 停在 708.75。其物理、native 用量等证据审计通过，但正式终点门禁失败；失败轨迹和成本全部保留。其他五条完成批次均为 1。每组最多三次尝试，不能用完成样本筛选出普遍质量优势。','','## S1：一小时、每臂 n=1','','来源为 `s1/stage-s1/w5/` 的最终正式 summary 和 audit；两臂都从 702 到 4302，均 registered_end，失败、拒绝与未知用量均为 0。','','| 指标 | Δ=300 | Δ=900 |','|---|---:|---:|']
 arms=[next(r for r in runs if r['name']=='formal-S1-'+arm)['totals'] for arm in ('d300','d900')]
 for label,key in [('Δ','delta_seconds'),('Δ_min','delta_min_seconds'),('H','horizon_seconds')]:lines.append(f'| {label}（秒） | {parameters["d300"][key]} | {parameters["d900"][key]} |')
 for label,key in [('会话','sessions'),('真实请求','requests'),('输入 tokens','input_tokens'),('缓存输入 tokens','cached_tokens'),('输出 tokens','output_tokens'),('完成批次','throughput'),('加权迟交','weighted_tardiness'),('可避免空闲积分（秒）','avoidable_idle_seconds'),('未缓存等价输入','uncached_equivalent_input_tokens')]:lines.append(f'| {label} | {display(arms[0][key])} | {display(arms[1][key])} |')
 lines += ['','浮点展示保留至小数点后三位，JSON 保留原值。两臂同时改变 Δ、Δ_min 和 H，不是只改 Δ 的单变量实验。Δ=900 的请求与输入较少，同时完成批次从 2 降为 1，可避免空闲积分更高。两臂通过各自登记的质量门禁，不表示两者业务质量相同，也不足以证明更大的 Δ 普遍更好。缓存输入是总输入的子集；未缓存等价输入采用 0.1 研究权重，不是账单价格。','','## 模型、工程验收与未完成事项','','模型从前一阶段的 `gpt-6-astra` 切换为 `gpt-6.1-sol`；官方 Codex 0.163.0、medium reasoning。协议/工具可见性、客户端模型目录和输出约束也发生变化，不能把跨版本差异归因于 Harness 单一改动。explicit 格式沿用 astra 的选择，尚无 sol 专属 A/B 格式证据。','','W5 按授权跳过了部分离线种子、六参考最坏状态搜索及整小时 mock/恢复验收。正式运行通过最终审计，不会补足这些跳过项。原始阶段报告保留了早期 blocked 与 ready/not-started 状态，应结合最终 summary、audit 和 pipeline-complete 读取。CQT/Q-time 未实现，八小时 S2 尚无本次完成证据，正式恢复仍需要单独验收。','','审计提速工作的文本代码、测量与比较记录保存于公开包 `s1/audit-opt/`；二进制 profiler 文件列入排除清单，原工作目录未改。本次仅汇总捕获时已落盘的 comparison 文件；完整最终速度报告尚未发现，不能把进行中的测量写成最终提速结论。归档没有重跑审计或实验。','','[源码比对](verification/source-comparison.json) 显示捕获的原始 Harness 源码与已有 10-17 目录逐字相同，且两份最终 amendment 冻结的 Harness 源码哈希全部匹配；无新增差异副本。阶段驱动、审计优化候选和历史 diff 保存在证据包中。','','本次只准备本地归档，不提交、不推送、不创建 PR 或 Release、不调用实验模型。公开包待人工复核及上传。','']
 (DEST/'README.md').write_text('\n'.join(lines))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);main(p.parse_args().output)
