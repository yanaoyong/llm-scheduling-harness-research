# Mac 命令式验收与 E1/P2 实验手册

从本目录（V6）运行；所有工作产物放在仓库外的 `$WORK`。步骤 0–4 不调用真实模型；
步骤 5、6 的 smoke、8 会调用模型，执行前须已有对应预算授权。此手册提供操作命令，
不声称真实 Codex 的 flags、Responses SSE、压缩事件已在开发机验证。
任一步失败就保留目录和日志，修复对应输入/协议后用新目录重跑，不能把失败项改成 passed。

## 0. 固定环境、版本和输入

先检出交付分支 `feat/harness-v6-codex-runner`，记录 commit。将下列路径改成自己的绝对路径；
`PIN` 必须为已选定 Codex 的完整 `--version` 输出，`MODEL` 为已批准模型名。
物理项目要含 `src/smt/environment.py`、固定 PySCFabSim vendor 和 SMT2020_LVHM 数据；
封存 evidence 使用此前交付的公开 extract 目录结构。不能用其他数据集替代。

```bash
export PHYSICAL=/absolute/physical-project
export DATA="$PHYSICAL/data/smt/SMT2020_LVHM"
export VENDOR="$PHYSICAL/vendor"
export EVIDENCE=/absolute/evidence
export WORK=/absolute/v6-phase-p
export CODEX=/absolute/pinned/codex
export PIN='完整的已固定版本输出'
export MODEL='已批准的模型名'
export TRUSTED_HASHES=/absolute/trusted-input-sha256.json
mkdir -p "$WORK"
python3.12 -m venv "$WORK/venv"
source "$WORK/venv/bin/activate"
python -m pip install pytest tiktoken==0.14.0
export TIKTOKEN_CACHE_DIR="$WORK/tiktoken-cache"
# 在允许下载的准备阶段预热；随后离线验收不下载。
python -c 'import tiktoken; tiktoken.get_encoding("o200k_base")'
export PYTHONPATH="$PWD/src:$PHYSICAL"
git rev-parse HEAD > "$WORK/commit.txt"
python scripts/mac_preflight.py --physical-root "$PHYSICAL" --data-dir "$DATA" \
  --vendor-dir "$VENDOR" --evidence-root "$EVIDENCE" --hash-manifest "$TRUSTED_HASHES" \
  --codex-binary "$CODEX" --codex-version "$PIN" --tiktoken-version 0.14.0 \
  --output "$WORK/preflight.json"
```

可信 hash 清单来自输入包发布方/已验收归档，格式是四个非空对象：
`{"physical":{"src/smt/environment.py":"SHA256",...},"data":{"相对文件":"SHA256",...},"vendor":{...},"evidence":{...}}`。
必须列出使用的所有数据/vendor/证据文件，不能把当前文件自算的 hash 当成来源认证。
脚本逐文件流式核对，拒绝越界路径，核对分支、Python 3.12/3.13、venv、tokenizer/cache 和 Codex pin。
预期全部 PASS、退出 0；失败修复路径/版本/缺件，保留 `preflight.json` 和 stderr。
**`codex --version` 只证明版本，不证明登录。** 用户已有 `codex exec` 登录能力是前置条件；
本脚本不做收费认证请求。实际认证在步骤 6 的独立 smoke 中验证。

## 1. 构建公共及封存夹具、题集

```bash
python scripts/build_public_fixture.py --data-dir "$DATA" --output "$WORK/public.json"
python scripts/build_sealed_fixture.py --evidence-root "$EVIDENCE" \
  --public-fixture "$WORK/public.json" --output "$WORK/sealed"
python scripts/validate_sealed_fixture.py "$WORK/sealed" > "$WORK/fixture-validation.log" 2>&1
export V6_MAC_FIXTURE="$WORK/sealed/fixture.json"
export V6_SEALED_DB="$WORK/sealed/contexts.sqlite"
export V6_SEALED_SELECT='SELECT group_name,payload FROM contexts'
export V6_CLASSIFICATION_REPORT="$WORK/classification-p.json"
python scripts/ab_comprehension.py generate --fixture "$V6_MAC_FIXTURE" --database "$V6_SEALED_DB" \
  --states g0 public:702 public:703 --seed 7 --per-type 12 --repetitions 2 --output "$WORK/ab-kit"
# 从现有题集提示提取精确快照，不把问题/答案发给开销探针。
python - <<'PY'
import os,json
from pathlib import Path
root=Path(os.environ['WORK'])/'ab-kit'
plan=json.loads((root/'presentation_plan.json').read_text())
for fmt in ('explicit','dense'):
    row=next(r for r in plan if r['state']=='g0' and r['format']==fmt)
    text=(root/row['prompt']).read_text()
    snapshot=text[text.index('SNAPSHOT_'):].split('\nQUESTIONS\n')[0]
    (root/(fmt+'-snapshot.txt')).write_text(snapshot)
PY
```

预期 fixture/provenance/build_summary/contexts.sqlite 产生且验证退出 0；G0 1649.82、public 702/703，
252 题、12 次 counterbalanced 请求。查看 coverage.json：实际独立目标数量/重复、near-miss 缺类必须披露。
失败不要改答案或封存数据，发送 build_summary、provenance、验证日志及错误。

## 2. 离线 suite

```bash
env -u V6_MAC_FIXTURE -u V6_SEALED_DB -u V6_F6_PROBE_DIR -u V6_SINGLE_ACTION_PROBE_DIR \
  PYTHONPATH="$PWD/src" python3 -m pytest -q > "$WORK/plain.log" 2>&1
python -m pytest -q > "$WORK/configured.log" 2>&1
date -u
```

预期零失败。Phase O 基线 plain 423 passed/45 skipped、configured 456 passed/12 skipped；
P 新增及 P0 合并后的精确数量见交付 `PHASE_P_REPORT.md`（系统 Python 是否已有 tiktoken 会改变 plain skips）。
配置完整时仅 12 项真实 Codex 证据测试可跳过，不能跳过物理、封存或 tokenizer 测试。
离线 fake 探针需要 loopback socket 权限；它们只使用 `tests/fake_codex.py`，不访问外部服务。
失败发送两个完整日志及 classification-p.json；先解决再继续。

## 3. 固定真实二进制的本地 mock 探针

```bash
python scripts/run_codex_probes.py --codex-binary "$CODEX" --codex-version "$PIN" --output "$WORK/probes"
export V6_F6_PROBE_DIR="$WORK/probes"
export V6_SINGLE_ACTION_PROBE_DIR="$WORK/probes"
python -m pytest -q tests/test_mac_session.py tests/test_mac_single_action.py
```

预期 12 个 PASS 和 12 passed，manifest `real_model_requests=0`，真实 binary 的 `mechanism_only=false`。
每项保留 command、prompt、schema、原始 session.jsonl、stderr、requests.jsonl、check.json；
MCP 项还保存进程启动/工具调用/结果证据，大结果从**下一轮请求**取回并核对完整 SHA256。
超时项必须在宿主截止前出现明确 MCP timeout，不能用宿主杀进程当作通过。
压缩项必须有真实可识别事件；不支持的 SSE/参数/JSONL 都应 FAIL，需修订适配器并全部复验。
单动作非法工具项仅返回未广告工具名，绝不执行 shell 来伪造证据。

实际 provider 配置为 `-c model_provider="v6_mock"`、
`model_providers.v6_mock.name="V6 loopback mock"`、`base_url="http://127.0.0.1:随机端口/v1"`、
`wire_api="responses"`、`requires_openai_auth=false`、`request_max_retries=0`、`stream_max_retries=0`
（后六个键均在 `model_providers.v6_mock.` 下）。runner 不继承 HOME/认证环境，拒绝非 loopback URL。
**以上 provider 键，以及 --ignore-user-config/--ignore-rules、原生工具关闭、环境继承和压缩设置，
均须由本步骤在实际 pin 上验证，开发机仅验证 fake 协议。** 不要在失败后切换真实 provider。
发送整个 probes 目录；请求日志可能含绝对路径，分享前检查，但不要删改审计原件。

## 4. 请求开销录制与登记值

设置拟采用的上下文/输出预算和最大工具轮次；必须来自批准的模型容量与实验预算。
`ROUNDS` 至少覆盖登记 `session_budget.max_tool_calls`（最坏每个调用单独一轮）。
示例不替用户决定预算：通过 shell `read` 输入。

```bash
read -r -p 'context_token_budget: ' CONTEXT
read -r -p 'output_reserve_tokens: ' RESERVE
read -r -p '最大工具轮次/max_tool_calls: ' ROUNDS
export CONTEXT RESERVE ROUNDS
for MODE in single_action mcp_session; do
  python scripts/measure_request_overhead.py --capture "$MODE" \
    --codex-binary "$CODEX" --codex-version "$PIN" --model "$MODEL" \
    --capture-rounds "$ROUNDS" --capture-dir "$WORK/overhead-$MODE-recording" \
    --snapshot "explicit=$WORK/ab-kit/explicit-snapshot.txt" \
    --snapshot "dense=$WORK/ab-kit/dense-snapshot.txt" \
    --context-token-budget "$CONTEXT" --output-reserve-tokens "$RESERVE" \
    --output "$WORK/overhead-$MODE.json"
done
```

预期两份 JSON 的 passed=true；查看每轮 system/instructions、tool schema、snapshot、其他输入、增长。
MCP 广告与生产相同三个工具 schema；mock 返回完整当前快照对象作为保守工具结果压力输入，
不表示物理 `read_entities` 的真实回答。多轮使用完整历史；若实际 Codex 用 opaque/previous_response_id
等无法计数格式，分析必须拒绝，不能当成零开销。
推荐值是两格式、已录制轮次中的最大非快照输入；登记两个模式结果的最大值，
检查 snapshot+overhead+reserve≤context。这是录制范围内的保守上界，**不是任意未来状态/任意工具输出的数学上界**；
有更大的 WIP/工具输出或更多轮次须增加压力录制并更新登记，真实服务不可见 framing 仍需 smoke 用量核对。
若预算失败，不裁剪快照；降低经批准的工具预算或调整容量并重新录制。
发送两个 JSON 和两个 recording 目录。也可用原有 `--requests explicit=... --requests dense=...` 纯分析入口复算。

## 5. A/B 理解（本步骤开始调用真实模型）

先固定统计决策规则并保存在 `$WORK/ab-decision.txt`：默认保守规则是 dense 每一题型准确率均不低于
explicit，且完整请求输入 token 均值更低；缺失/失败请求或未知用量时不选 dense。样本小或结果混合时
保留 explicit 或另行授权增加重复次数，不由 harness 自动选格式。用户可事先登记其他容差，禁止看结果后改规则。

```bash
python - <<'PY'
import json,os
from pathlib import Path
w=Path(os.environ['WORK'])
a=[json.loads((w/('overhead-'+m+'.json')).read_text()) for m in ('single_action','mcp_session')]
assert all(r['passed'] for r in a)
(w/'overhead-max.txt').write_text(str(max(r['request_overhead_tokens'] for r in a)))
PY
export OVERHEAD="$(cat "$WORK/overhead-max.txt")"
printf '%s\n' 'dense 每题型准确率不低于 explicit，完整请求输入均值更低，零缺失且用量已知；否则 explicit。' > "$WORK/ab-decision.txt"
python scripts/ab_comprehension.py run --kit "$WORK/ab-kit" --output "$WORK/ab-run" \
  --codex-binary "$CODEX" --codex-version "$PIN" --model "$MODEL" \
  --context-token-budget "$CONTEXT" --request-overhead-tokens "$OVERHEAD" \
  --output-reserve-tokens "$RESERVE" --wall-seconds 300
python scripts/ab_comprehension.py score --questions "$WORK/ab-kit/questions.json" \
  --answers "$WORK/ab-run/answers" --output "$WORK/ab-score.json"
```

预期 12 次请求，同模型/预算/题集，仅 snapshot_format 变化；按 presentation_plan 执行 AB/BA 顺序。
run 不读取 answer_key；输出仅 answers 目录放 response JSON，其他证据单独保存。
score 输出逐题/题型/格式准确率与逐请求 usage；缺请求按错计分。任何失败保留目录，
不要只重跑失败格式来提高分数。重新试验要新目录、新的完整 counterbalanced plan。
发送 ab-kit（含独立答案用于审计）、ab-run、ab-score.json/.md、ab-decision.txt 和最终人工选择理由。

## 6. 真实物理 scripted dry-run、一次会话 smoke

先生成模板的机制版并运行；不用 fake executable，不调用模型。

```bash
python - <<'PY'
import json,os
from pathlib import Path
r=json.loads(Path('registration_template.json').read_text())
r.update(fixture=os.environ['V6_MAC_FIXTURE'],context_token_budget=int(os.environ['CONTEXT']),
         request_overhead_tokens=int(os.environ['OVERHEAD']),output_reserve_tokens=int(os.environ['RESERVE']))
(Path(os.environ['WORK'])/'dry-registration.json').write_text(json.dumps(r,sort_keys=True))
PY
python scripts/run_live.py --registration "$WORK/dry-registration.json" --group P2 --trajectory 1 \
  --output "$WORK/dry-physics" --dry-run-scripted --until 882
```

预期到 882s，manifest 标记“非模型、仅机制测试”，无失败/未知 usage、生产来自 scripted planner；
其 token 不是模型成本。失败发送 dry-physics，解决物理/预算问题再继续。
真实一次会话 smoke 同样要求明确预算/质量字段。先用下列命令填写独立 smoke 登记；步骤 7 再审核并冻结正式副本：

```bash
python -c '
import json,os
from pathlib import Path
from harness_v6.registration import validate
r=json.loads(Path("registration_template.json").read_text())
r.update(dry_run=False,is_result=True,plan_source="model",label="模型实验",fixture=os.environ["V6_MAC_FIXTURE"],
 codex_version=os.environ["PIN"],model=os.environ["MODEL"],context_token_budget=int(os.environ["CONTEXT"]),
 request_overhead_tokens=int(os.environ["OVERHEAD"]),output_reserve_tokens=int(os.environ["RESERVE"]),
 snapshot_format=input("snapshot_format (explicit/dense): ").strip(),
 per_sim_hour_token_cap=float(input("每模拟小时 token cap: ")),per_sim_hour_request_cap=float(input("每模拟小时 request cap: ")),
 env_allowlist=["PATH","HOME","PYTHONPATH","TIKTOKEN_CACHE_DIR"],breakdowns=False)
r["session_budget"]["max_tool_calls"]=int(os.environ["ROUNDS"])
r["session_budget"]["token_cap"]=int(input("累计 session input+output token_cap: "))
r["session_budget"]["wall_seconds"]=float(input("session wall_seconds: "))
for name in r["quality"]:
 r["quality"][name]={"floor":float(input(name+" floor: ")),"tolerance":float(input(name+" absolute tolerance: "))}
assert not validate(r,results=True),validate(r,results=True)
(Path(os.environ["WORK"])/"smoke-registration.json").write_text(json.dumps(r,sort_keys=True,indent=2)+"\n")
print(json.dumps(r,ensure_ascii=False,indent=2))'
```

```bash
python scripts/run_live.py --registration "$WORK/smoke-registration.json" --group P2 --trajectory 1 \
  --output "$WORK/smoke" --codex-binary "$CODEX" --max-sessions 1
```

预期 summary.totals.sessions=1、failures=0、unknown_usage=0、stop_reason=session_limit，提交被采纳；
核对实际 usage、JSONL/MCP 审计与上下文预算。认证失败修复用户登录和 env_allowlist，不在 harness 内管理凭据。
smoke 不纳入最终六条轨迹。发送 smoke 目录，预算超限/压缩/失败先停，不自动重试。

## 7. 填全并验证登记

审核步骤 6 已问答填写的全部字段，复制为正式登记。费用与质量数字由用户决定。
ENV allowlist 默认 PATH/HOME/PYTHONPATH/TIKTOKEN_CACHE_DIR；API-key 登录才另加所需变量**名称**，不保存值。

```bash
cp "$WORK/smoke-registration.json" "$WORK/registration.json"
python -c 'import os; from harness_v6.registration import load; load(os.environ["WORK"]+"/registration.json",results=True); print("registration PASS")'
```

如调整任何字段，先用更新的登记重新做独立 smoke，再冻结最终文件。

逐字段核对完整清单（不允许遗漏 null）：

| 字段 | 含义/首轮值 |
|---|---|
| stage, delta_seconds, delta_min_seconds, horizon_seconds | S0,60,60,900 |
| groups, group_configs | E1=event/single_action；P2=periodic/mcp_session |
| trajectories_per_group, trajectory_seeds | 3；[1,2,3]；工厂 seed，不是模型 seed |
| fixture, fixture_key, end_time | 绝对 fixture、mixed_702、1603.1 |
| dry_run, is_result, plan_source, label | false,true,model,模型实验 |
| model, codex_version, snapshot_format | 同一 pin/model、事前选择格式 |
| context_token_budget, request_overhead_tokens, output_reserve_tokens | 容量、双模式最大录制上界、输出+推理预留 |
| session_budget.max_tool_calls/wall_seconds/token_cap | 工具上限、墙钟、累计 input+output 上限（不是输出预留） |
| per_sim_hour_token_cap, per_sim_hour_request_cap | 事前批准的每模拟小时上限 |
| quality.weighted_tardiness/throughput/avoidable_idle_integral.floor/tolerance | 绝对上/下界及相对 E1 的绝对容差；throughput 越高越好，其他越低越好 |
| failure.keep_old_plan/adopt_crashed_submission/retry/k_fail/unknown_usage_cap | true/false/false/2/2 |
| cached_input_weight, counting_basis, primary_metrics | 0.1、累计 session usage/request 下界、未缓存等价输入及请求下界/模拟小时 |
| steady_state_window.exclude_first_hours | 首轮 0；S1+ 预先排除爬坡小时 |
| env_allowlist | 实际运行必需的变量名，不是密钥值 |
| breakdowns | S0 false；S2+ true |
| 可选 segment_seconds/segment_cycles | 默认 3600/60，周期完成仍持久化 |
| 可选 drift_rule | 如启用，字段/语义见 CycleConfig/DriftRule；必须事前登记，首轮省略 |

核对后登记文件冻结；更改登记必须用新 run 目录，不可对旧轨迹 resume。质量 floor/tolerance 没填不能运行。
发送最终 registration.json、输入 hash 清单及授权预算说明。smoke 必须已通过且与最终字段一致。

## 8. E1/P2 各三条轨迹

```bash
for GROUP in E1 P2; do
  for K in 1 2 3; do
    python scripts/run_live.py --registration "$WORK/registration.json" --group "$GROUP" --trajectory "$K" \
      --output "$WORK/runs/$GROUP-$K" --codex-binary "$CODEX" || break 2
  done
done
# 仅恢复指定中断轨迹，登记、fixture、pin 不变：
# python scripts/run_live.py --registration "$WORK/registration.json" --group E1 --trajectory 1 \
#   --output "$WORK/runs/E1-1" --codex-binary "$CODEX" --resume
```

每条预期 end=1603.1、stop_reason=registered_end；任何失败/预算停止都需保留并分析，不能删除重抽。
中断会话不重跑、不采用崩溃 submission，成本未知按登记计数；完成会话已有检查点。
用 smoke 的均值估算：墙钟≈预计会话数×每会话秒数；请求≈会话×(平均工具轮次+1)；
未缓存等价输入≈Σ(input−cached×(1−cached_input_weight))；价格估算用用户当前合同单价分别乘
未缓存输入、缓存输入、输出（除以报价单位），再乘六条轨迹，不在代码中硬编码价格。
窗口模拟小时=(1603.1−702)/3600；每小时上限×窗口小时给出预算参考，闸门在段/终点检查，并非每请求硬限。
发送六个 run 目录（checkpoint/压缩 trace/MCP/JSONL/manifest/summary），不要仅发聚合数值。

## 9. 汇总与回传

```bash
python scripts/summarize_runs.py "$WORK/runs/E1-1" "$WORK/runs/E1-2" "$WORK/runs/E1-3" \
  "$WORK/runs/P2-1" "$WORK/runs/P2-2" "$WORK/runs/P2-3" --output "$WORK/results"
date -u > "$WORK/finished-at.txt"
```

预期 results.json/results.md：组均值/标准差、稳态与全程指标、预算/失败/未知用量、E1/P2 请求与
未缓存等价输入比较、质量 floor/tolerance。不得混合 dry-run、smoke、不同登记；少于三条或未到终点只能报不完整证据。
回传 `$WORK` 中上述各步骤指定文件及最终 results；认证文件/API key 不在回传范围。
G0 是封存参照，不据此推断新轨迹调用数。CQT/Q-time 未实现，不能解释为已满足相关质量约束。
