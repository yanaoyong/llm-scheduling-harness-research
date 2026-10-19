# Mac 预检输入的可信 SHA-256 清单

本次交付的是 Mac 预检实际使用的[原始清单](evidence/trusted-input-sha256.json)，按原始字节复制，未从接收方镜像重新生成，也未改写路径、排序或 JSON 格式。清单仅包含四类输入的相对文件名和 SHA-256，不包含输入文件正文。

文件大小：**6,234,964 字节**。清单自身 SHA-256：

```text
d2205351e4368d6d600dd915ee61ca31f882d9762833aa74924b17ca34a70fd9
```

| 根目录类别 | 文件数 | 相对路径基准 |
|---|---:|---|
| physical | 3 | 物理项目根，包含 `src/smt/environment.py` |
| data | 20 | `SMT2020_LVHM` 数据目录 |
| vendor | 26 | vendor 根，包含 `PySCFabSim-revised/simulation/` |
| evidence | 27,998 | 已交付公开 evidence 的 extract 根，包含 `fixtures/`、`live_pilots/` |
| 合计 | **28,047** | 四个根目录分别映射，不拼接成一个公共根 |

来源依据是同批保存的[历史完整性报告原件](verification/mac-step34-input-integrity.json)：它已记录上述清单哈希、四类数量和 28,047 项通过。此次还逐项交叉核对了五份历史预检记录中的文件名、期望哈希和通过状态，并使用原有 `mac_preflight.hashes()` 重新核验 Mac 输入；结果见[来源核验记录](verification/trusted-input-provenance.json)。预检报告的 28,054 项包含 7 项环境检查，输入文件数仍为 28,047。

## 接收方只读核验

拉取合并后的提交后，从仓库根目录设置路径：

```sh
export TRUSTED_HASHES="$PWD/docs/updates/2026-10-19/evidence/trusted-input-sha256.json"
export PHYSICAL=/absolute/physical-project
export DATA="$PHYSICAL/data/smt/SMT2020_LVHM"
export VENDOR="$PHYSICAL/vendor"
export EVIDENCE=/absolute/evidence
```

下面仅核验清单和输入字节，调用仓库已有的哈希检查函数；不会启动 Codex、模拟器或模型，也不替代环境、协议和新版本验收。

```sh
python3 - <<'PY'
import hashlib, importlib.util, json, os, sys
from pathlib import Path

manifest_path = Path(os.environ['TRUSTED_HASHES'])
raw = manifest_path.read_bytes()
wanted = 'd2205351e4368d6d600dd915ee61ca31f882d9762833aa74924b17ca34a70fd9'
if hashlib.sha256(raw).hexdigest() != wanted:
    raise SystemExit('FAIL: trusted manifest SHA-256 mismatch')
manifest = json.loads(raw)
counts = {category: len(entries) for category, entries in manifest.items()}
if counts != {'physical': 3, 'data': 20, 'vendor': 26, 'evidence': 27998}:
    raise SystemExit('FAIL: trusted manifest categories/counts mismatch')
v6 = Path('docs/updates/2026-10-17/project/experiments/harness_v6_20261017').resolve()
sys.path.insert(0, str(v6 / 'src'))
spec = importlib.util.spec_from_file_location('mac_preflight', v6 / 'scripts/mac_preflight.py')
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)
roots = {key: os.environ[env] for key, env in (
    ('physical', 'PHYSICAL'), ('data', 'DATA'), ('vendor', 'VENDOR'), ('evidence', 'EVIDENCE'))}
checks = preflight.hashes(manifest, roots)
failed = [{'name': name, 'detail': detail} for name, passed, detail in checks if not passed]
passed = len(checks) == 28047 and not failed
print(json.dumps({'passed': passed, 'checked_files': len(checks), 'failed': failed}, ensure_ascii=False))
raise SystemExit(0 if passed else 1)
PY
```

预期 `passed=true`、`checked_files=28047`、`failed=[]`、退出码 0。缺件或哈希差异必须保留并解决；不得把本机重算值写回可信清单来消除差异。通过仅证明清单列出的输入与 Mac 预检输入逐字节一致，目录内新增文件和新实验另外引入的输入仍需单独登记。完整环境预检沿用 [Mac runbook 步骤 0](../2026-10-17/project/experiments/harness_v6_20261017/MAC_RUNBOOK.md)，将 `--hash-manifest` 指向本文件。

## 官方版迁移与实验口径

S0 使用专用 Codex 构建。切换官方版后，工具清单、请求上限的实现方式和 Codex 版本均发生变化，因此 S0 的 A/B 准确率、调用次数和成本仅可作背景参考，不能直接与新实验作同条件比较，也不能沿用旧登记宣称新版本已通过。

正式结论以新登记下完成验收的六条轨迹（E1/P2 各三条）为准。先完成受影响的离线与协议验收、匹配 smoke，并在正式运行前冻结新登记；不得看正式结果后修改判定规则。本次只交付输入来源清单及说明，不启动真实调用。按既定分工，第 1 步由 Codex 实现，验收方负责验收；本次清单交付不代表第 1 步实现或验收已经完成。
