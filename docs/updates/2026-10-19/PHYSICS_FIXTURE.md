# 独立物理审计模块与原始封存夹具

按用户指定的两项路径补交 Mac 原件，文件位于 [`evidence/physics-fixture/`](evidence/physics-fixture/)。本次只复制、压缩和核验，不重新生成夹具、不执行模拟器或真实模型。

| 所需路径（相对实验 WORK） | Git 中的交付内容 |
|---|---|
| `goal-s0-20261019/independent_physics/` | 同名目录完整 5 文件：`__init__.py`、`audit.py`、`audit_prefix.py`、`source_check.py`、`manifest.json` |
| `sealed/fixture.json` | `sealed/fixture.json.gz`，解压后恢复原文件 |

夹具原件为 **226,952,512 字节**，超过 [GitHub 普通 Git 的 100 MiB 单文件上限](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)。因此本 PR 提交无损 gzip：**43,821,896 字节**，无需 Git LFS 或额外 Release 下载。

- 原始 `fixture.json` SHA-256：`d76827abb88c0ffdfbf4770a3b9fd4a119ff5416dd61deb968761a334e4ecd69`
- `fixture.json.gz` SHA-256：`7333bb764d778f60b31cf6da4e22c97e53d8810eac0dd9d4b03b4bba2e8b37f8`
- 完整逐文件大小、原始哈希、Git 存储哈希及来源绑定见[补交清单](evidence/physics-fixture/manifest.json)。

独立模块的 5 个文件均与 Mac 原件逐字节一致。`audit.py`、`source_check.py` 与原始 `independent_physics/manifest.json` 的来源哈希一致；`audit_prefix.py` 与已有独立物理验收记录一致。夹具解压后的哈希与 S0 正式及 smoke 登记中的 `fixture_sha256` 一致，也满足旧 `audit_physical_prefix.py` 对 `run_manifest.fixture_hash` 的原字节检查。

以下恢复命令已实际执行并与 Mac 原件逐块比较；详细结果见[补交核验记录](verification/physics-fixture-handoff.json)。

## 恢复到仓库外

从仓库根目录执行，先把 `RESTORED_WORK` 改为仓库外一个尚不存在的目录。恢复命令不会覆盖已有目录；执行结束后，把已核验的文件交给现有实验工作目录即可。

```sh
export PHYSICS_SUPPLEMENT="$PWD/docs/updates/2026-10-19/evidence/physics-fixture"
export RESTORED_WORK=/absolute/path/outside-repository/restored-mac-inputs
python3 - <<'PY'
import gzip, hashlib, json, os, shutil
from pathlib import Path

source = Path(os.environ['PHYSICS_SUPPLEMENT']).resolve()
target = Path(os.environ['RESTORED_WORK']).resolve()
if target.exists() or target.is_relative_to(Path.cwd().resolve()):
    raise SystemExit('Choose a new destination outside the repository')
rows = json.loads((source / 'manifest.json').read_text())['files']
def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()
for row in rows:
    src = (source / row['stored_path']).resolve()
    dst = (target / row['restored_path']).resolve()
    if not src.is_relative_to(source) or not dst.is_relative_to(target):
        raise SystemExit('Unsafe manifest path')
    if sha(src) != row['stored_sha256']:
        raise SystemExit('Stored file hash mismatch: ' + row['stored_path'])
for row in rows:
    src = source / row['stored_path']
    dst = target / row['restored_path']
    dst.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if row['encoding'] == 'gzip' else open
    with opener(src, 'rb') as reader, dst.open('xb') as writer:
        shutil.copyfileobj(reader, writer, 4 * 1024 * 1024)
    if dst.stat().st_size != row['bytes'] or sha(dst) != row['sha256']:
        raise SystemExit('Restored file hash mismatch: ' + row['restored_path'])
print(json.dumps({'passed': True, 'files': len(rows), 'model_calls': 0}))
PY
```

预期输出 `passed=true`、`files=6`。独立模块保留原相对导入关系，需要将其父目录 `goal-s0-20261019` 放入审计进程的模块搜索路径；现有 Release 的 `goal/` 是该工作目录的归档别名，恢复时应与审计入口脚本放在同一层。

## 原始哈希与跨机路径

这次交付保留用户指定原件的全部字节，包括夹具 `data_dir`、`mechanism_results` 的 4 处 Mac 路径，以及模块来源清单中的历史路径；不把它们改写成占位符，否则冻结的夹具哈希不再匹配。源代码和夹具中没有发布凭据或认证目录。

恢复完成只证明原始输入和模块已到齐，不代表 Mac 路径能在另一台机器直接使用。跨机执行应在执行适配层建立本地路径映射，保留原件供哈希验证，不通过改写旧登记哈希来规避检查。其他封存依赖（例如 `contexts.sqlite`、物理数据、已有运行目录）仍使用各自的可信输入与交付记录；本 PR 没有重写它们，也没有放宽审计标准。

S0 仍是历史专用构建的结果；官方版迁移后的正式结论以新登记下六条轨迹为准。
