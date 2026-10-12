"""transcript_lean —— Claude Code 会话 raw JSONL 的 lean 提取 + secret 脱敏纯函数库。

本模块是变更卡 feat-transcript-archive-20260717 任务 T1 的交付物：对**单会话** raw
JSONL 行流做确定性 lean 变换（截断噪声 / 折叠重复注入块 / 丢弃噪声行）并对全部字符串值做
secret 脱敏，供 CLI（transcript_archive.py · T3）与守护测试（T7）作纯函数库调用。

设计铁律
--------
1. **确定性 / 幂等**：同一输入 → 逐字节相同输出。禁止在输出中引入时间戳、随机数、无序遍历
   （dict/set 迭代顺序）等不确定来源。元数据头用 ``sort_keys=True`` 序列化；变换后的行保留输入
   的键顺序（json.loads 保序）不再排序。
2. **纯 stdlib（Python 3.11+）**：零第三方依赖；**不调用任何外部二进制 / 加密工具**。
3. **不内嵌任何真实密钥**（GEN-3 / CODE-005）：正则只含前缀字面（如 ``sk-ant-``），样例密钥值
   留给 T7 守护测试构造。

lean 变换规则（spec §附录 A 冻结契约，逐条实现，落点见各函数 docstring）
--------------------------------------------------------------------------
| 行类型                                   | 处理                                            |
|-----------------------------------------|------------------------------------------------|
| user 消息                                | 逐字保留（仍过 secret 脱敏）                     |
| assistant 文本                           | 保留                                            |
| assistant thinking                       | 保留（HITL-1 已裁：保留）                        |
| tool_use                                 | 保留工具名 + 参数；参数 >truncate_bytes 截断（记原始长度）|
| tool_result                              | 截断至首 truncate_bytes + 记原始长度 + 被截部分 sha256 |
| attachment/file-history-snapshot/queue-operation | 整行丢弃（噪声类型）                     |
| 重复 ``[harness:prompt_state]`` 注入块    | 仅保首次；后续折叠为一行标记                      |
| JSONL 信封字段（gitBranch/timestamp/cwd/sessionId 等）| 逐字保留；仅对含 secret 的值过脱敏     |
| 全行统一                                  | 过 secret 脱敏（命中→``【REDACTED:<类型>】`` + 计数入元数据头）|

多字节 UTF-8 切点安全：截断永远在码点边界回退，不切出半个码点、不抛异常。

第二检测器（AC-2 · 与脱敏正则族**不同源**，供 T7 全量扫描）
------------------------------------------------------------
- ``hard_gate_scan``（硬门层）：独立维护的 secret ruleset **超集**（覆盖脱敏漏网族
  如 ``xoxb-`` / ``glpat-`` / 私有云 token）。与脱敏族不共享变量。脱敏开启后对 lean 产物
  扫描命中须 =0（正控）；对未脱敏 raw 扫描须 >0（负控，证明扫描器非惰性）。
- ``entropy_scan``（告警层）：高熵字符串启发（base64/hex 段 Shannon 熵）。允许命中 >0、
  **不进硬门**。良性高熵白名单（C-3）**按 JSON 字段位置 / provenance 匹配、禁按纯值形态匹配**：
  仅豁免归档管线自身写入已知信封 / 元数据字段位置的高熵串（元数据头 / ``sha256`` 字段 /
  ``sessionId`` 信封字段 / git SHA 信封字段）；同形态高熵串若出现在 user/assistant/tool_use/
  tool_result 内容正文位置照常告警。

ReDoS / 灾难回溯缓解（LOW-1 定性）
---------------------------------
消费方 denylist 为**消费方自撰**正则，ReDoS 属其**自伤面**，本库做**尽力缓解**：
(1) denylist 逐条 ``re.compile``，编译失败条目 skip+warning、**不中止**，内置族仍生效（fail-safe）；
(2) 对 denylist 匹配加**确定性行级长度护栏**（``DENYLIST_MAX_LINE_CHARS``）——超长字符串
    直接跳过 denylist 匹配（内置族仍跑），使病态回溯正则在超长行上 match-time 有界返回。
不采用超时护栏：超时结果随机器速度而变、会破坏本库的确定性铁律，故弃用。护栏阈值**内**的中等长
行仍可能灾难回溯，此为消费方自撰正则的固有自伤面、非本库可根除，见上定性。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from math import log2
from typing import Iterable

# --------------------------------------------------------------------------- #
# 冻结常量
# --------------------------------------------------------------------------- #

DEFAULT_TRUNCATE_BYTES = 2048
"""tool_use 参数 / tool_result 内容的默认截断字节阈值（HITL-1 裁定 2 KB）。"""

LEAN_SCHEMA = "harness-transcript-lean/v1"
"""lean 元数据头 schema 标识，随格式演进 bump。"""

PROMPT_STATE_MARKER = "[harness:prompt_state]"
"""重复注入块识别锚（standalone 注入块以此开头）。"""

PROMPT_STATE_FOLD_MARKER = "[harness:prompt_state:folded]"
"""重复注入块折叠后的一行占位标记。"""

# 噪声**行**类型（顶层 type 字段命中 → 整行丢弃）。
NOISE_LINE_TYPES = frozenset({"attachment", "file-history-snapshot", "queue-operation"})
# 噪声**内容块**类型（message.content[*].type 命中 → 丢该块，与上并列的防御性一致处理）。
NOISE_BLOCK_TYPES = frozenset({"attachment"})

# denylist 匹配行级长度护栏（字符数 · 确定性 ReDoS 缓解）。
DENYLIST_MAX_LINE_CHARS = 4096

# 高熵告警参数（告警层，不进硬门）。
ENTROPY_MIN_RUN_LEN = 24
ENTROPY_THRESHOLD = 3.5  # bits/char

# 良性高熵白名单（C-3 · **按字段键 / provenance 匹配，非按值形态**）：
# 仅豁免归档管线写入的信封 / 元数据字段位置的高熵串。
PROVENANCE_WHITELIST_KEYS = frozenset({
    # lean 截断元数据字段（本库注入）
    "sha256",
    # 会话信封身份字段
    "sessionId", "session_id",
    "uuid", "parentUuid", "leafUuid", "requestId",
    # git 信封 SHA 字段
    "gitCommit", "gitSha", "commit",
})

_PLACEHOLDER_PREFIX = "【REDACTED:"
_PLACEHOLDER_SUFFIX = "】"


def _placeholder(type_name: str) -> str:
    return _PLACEHOLDER_PREFIX + type_name + _PLACEHOLDER_SUFFIX


# --------------------------------------------------------------------------- #
# 脱敏正则族（内置 · 命中即替换 + 计数）。与 hard_gate 的 ruleset **不同源**。
# 注：仅含前缀字面，绝不内嵌真实密钥值（GEN-3 / CODE-005）。
# --------------------------------------------------------------------------- #

# 私钥块：优先匹配完整 BEGIN…END；无 END（如被截断的 PEM 残块）则吞至字符串结尾，
# 杜绝截断后 preview 里残留 BEGIN + 部分 base64 逃过脱敏、进而被硬门层 FIRE。
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"
    r"[\s\S]*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)"
)

# 顺序敏感：``ANTHROPIC_KEY``（``sk-ant-`` 前缀）必须先于通用 ``SK_KEY``（``sk-`` 前缀），
# 否则 ``sk-ant-…`` 会被通用 SK_KEY 先命中、误归类（R-2 / AC-4）。
# C-1 不变量：每条脱敏规则的前缀字面 / charset / 长度下限均构造为对应 HARD_GATE_RULES 规则的
# **子集或相等**，使脱敏命中面 ⊆ 硬门命中面（逐条对应关系见 HARD_GATE_RULES 注释）。
BUILTIN_SECRET_RULES: list[tuple[str, re.Pattern]] = [
    ("ANTHROPIC_KEY", re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")),
    # 通用 sk-（DeepSeek 等 · UQ-3 阈值 N=20）——须置于 ANTHROPIC_KEY 之后。
    ("SK_KEY", re.compile(r"sk-[A-Za-z0-9_\-]{20,}")),
    # 原 ghp_ 规则保留（gh[pousr]_ 的子集）——ghp_ 命中先归 GITHUB_TOKEN，护既有守护快照。
    ("GITHUB_TOKEN", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
    # GitHub 全变体（classic ghp_/gho_/ghu_/ghs_/ghr_）——补齐 ghp_ 未覆盖的 o/u/s/r 变体。
    ("GITHUB_TOKEN_ALL", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    # GitHub fine-grained PAT——charset **无连字符**，与硬门 github_fine_grained 完全一致（C-1）。
    ("GITHUB_PAT", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("AWS_ACCESS_KEY", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("SLACK_TOKEN", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("GITLAB_PAT", re.compile(r"glpat-[A-Za-z0-9_\-]{16,}")),
    # Google API key——与硬门收紧后完全同边界同 charset（精确 35 位尾 + 词边界 · C-1 / C-3 B）。
    ("GOOGLE_API_KEY", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("PRIVATE_KEY", _PRIVATE_KEY_RE),
    ("BEARER_TOKEN", re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}")),
]

# --------------------------------------------------------------------------- #
# 硬门层 ruleset（AC-2 · **独立维护的超集**，独立定义、不 import 复用脱敏族变量）。
# 覆盖脱敏漏网族：GitHub 全变体 / AWS 临时 / Slack / GitLab / Google / 私钥标记 / Bearer。
# --------------------------------------------------------------------------- #

# 硬门 ⊇ 脱敏（C-1）：逐条为 BUILTIN_SECRET_RULES 的检测超集。
# 顺序：anthropic_key 先于 generic_sk（与脱敏族同序，护 sk-ant- 先命中）。
HARD_GATE_RULES: list[tuple[str, re.Pattern]] = [
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")),
    # 通用 sk（⊇ 脱敏 SK_KEY · 同 charset 同 {20,}）——须先于其后规则、后于 anthropic_key。
    ("generic_sk", re.compile(r"sk-[A-Za-z0-9_\-]{20,}")),
    ("github_classic", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("github_fine_grained", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("aws_access_key", re.compile(r"A(?:KIA|SIA)[0-9A-Z]{16}")),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("gitlab_pat", re.compile(r"glpat-[A-Za-z0-9_\-]{16,}")),
    # C-3 B 收紧：精确 35 位尾 + 词边界（Google key 精确 39 字符），杜绝嵌于长 base64 的伪命中。
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    # UQ-4 reconcile：下调至 {8,} 对齐脱敏 BEARER_TOKEN，恢复 8–15 长区间的 C-1 不变量。
    ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}")),
]


# --------------------------------------------------------------------------- #
# 数据类
# --------------------------------------------------------------------------- #

@dataclass
class DenylistResult:
    """load_denylist 结果。

    rules: list[tuple[str, re.Pattern]] —— 编译成功的 (类型名, 已编译正则)。
    skipped: list[tuple[int, str]] —— 编译失败 / 无法打开的 (行号, 错误串)，供 warning。
    """
    rules: list = field(default_factory=list)
    skipped: list = field(default_factory=list)


@dataclass
class LeanResult:
    """lean_transform 结果。

    lines: list[str] —— 首行=元数据头 JSON 行（含 schema + REDACTED 分类型计数 + 截断记录数），
            其后为逐行 lean JSON（噪声行已丢弃、重复注入块已折叠）。
    warnings: list[str] —— denylist 编译降级 / 长度护栏跳过 / 非法 JSON 行等非致命提示。
    """
    lines: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


class _Ctx:
    """单次 lean_transform 的可变累加器（不入输出、仅驱动确定性统计）。"""

    __slots__ = (
        "truncate_bytes", "counts", "truncated_records",
        "prompt_state_seen", "prompt_state_folded",
        "denylist", "denylist_guard_skips",
    )

    def __init__(self, truncate_bytes: int, denylist: DenylistResult | None):
        self.truncate_bytes = truncate_bytes
        self.counts: Counter = Counter()
        self.truncated_records = 0
        self.prompt_state_seen = 0
        self.prompt_state_folded = 0
        self.denylist = denylist
        self.denylist_guard_skips = 0


# --------------------------------------------------------------------------- #
# 字节安全截断
# --------------------------------------------------------------------------- #

def _byte_truncate(text: str, limit: int) -> tuple[str, str, int]:
    """把 text 按 UTF-8 字节数截断到 <= limit，返回 (保留串, 被截串, 原始字节数)。

    切点在码点边界回退，不切出半个多字节码点、不抛异常。limit<=0 → 全截。
    """
    data = text.encode("utf-8")
    orig_len = len(data)
    if orig_len <= limit:
        return text, "", orig_len
    if limit <= 0:
        return "", text, orig_len
    cut = limit
    # UTF-8 续接字节形如 0b10xxxxxx；若切点落在续接字节上，向前回退到码点起始。
    while cut > 0 and (data[cut] & 0xC0) == 0x80:
        cut -= 1
    kept = data[:cut].decode("utf-8")
    removed = data[cut:].decode("utf-8")  # cut 为码点边界 → 尾段必是合法 UTF-8
    return kept, removed, orig_len


# --------------------------------------------------------------------------- #
# denylist 装载
# --------------------------------------------------------------------------- #

def load_denylist(path: str | None) -> DenylistResult:
    """装载消费方可扩 denylist 文件，逐条 ``re.compile``。

    文件格式：每行一条正则；``可选类型名<TAB>正则`` 亦可（无 TAB 则类型名=``CUSTOM``）；
    ``#`` 起始行与空行忽略。**编译失败条目 skip 并记入 .skipped（不中止）**，内置脱敏族仍生效
    （fail-safe，不 fail-open 到无脱敏）。path=None → 空规则。文件无法打开亦 fail-safe 返回空规则。
    """
    if path is None:
        return DenylistResult(rules=[], skipped=[])
    rules: list[tuple[str, re.Pattern]] = []
    skipped: list[tuple[int, str]] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for lineno, raw in enumerate(fh, 1):
                line = raw.rstrip("\n")
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if "\t" in line:
                    name, pattern = line.split("\t", 1)
                    name = name.strip() or "CUSTOM"
                else:
                    name, pattern = "CUSTOM", line
                try:
                    compiled = re.compile(pattern)
                except re.error as exc:
                    skipped.append((lineno, f"re.compile failed: {exc}"))
                    continue
                rules.append((name, compiled))
    except OSError as exc:
        skipped.append((0, f"cannot open denylist {path!r}: {exc}"))
        return DenylistResult(rules=[], skipped=skipped)
    return DenylistResult(rules=rules, skipped=skipped)


# --------------------------------------------------------------------------- #
# 脱敏（递归覆盖所有字符串值）
# --------------------------------------------------------------------------- #

def _redact_string(s: str, ctx: _Ctx) -> str:
    result = s
    for name, pat in BUILTIN_SECRET_RULES:
        result, n = pat.subn(_placeholder(name), result)
        if n:
            ctx.counts[name] += n
    dl = ctx.denylist
    if dl and dl.rules:
        if len(result) <= DENYLIST_MAX_LINE_CHARS:
            for name, pat in dl.rules:
                result, n = pat.subn(_placeholder(name), result)
                if n:
                    ctx.counts[name] += n
        else:
            # 行级长度护栏：超长串跳过 denylist 匹配（内置族已跑），确定性地界定 match-time。
            ctx.denylist_guard_skips += 1
    return result


def _redact_obj(obj, ctx: _Ctx):
    if isinstance(obj, str):
        return _redact_string(obj, ctx)
    if isinstance(obj, list):
        return [_redact_obj(x, ctx) for x in obj]
    if isinstance(obj, dict):
        # 只脱敏值、不动键（键=结构字段名，须稳定）。
        return {k: _redact_obj(v, ctx) for k, v in obj.items()}
    return obj


# --------------------------------------------------------------------------- #
# 重复 [harness:prompt_state] 折叠（session 级计数）
# --------------------------------------------------------------------------- #

def _fold_obj(obj, ctx: _Ctx):
    """折叠重复注入块：**仅**折叠 standalone 注入块（lstrip 后以 marker 开头的字符串），
    首次保留、其后替换为一行标记。marker 嵌于用户散文中的字符串不折叠（护 user 逐字保留）。
    """
    if isinstance(obj, str):
        if obj.lstrip().startswith(PROMPT_STATE_MARKER):
            ctx.prompt_state_seen += 1
            if ctx.prompt_state_seen > 1:
                ctx.prompt_state_folded += 1
                return PROMPT_STATE_FOLD_MARKER
        return obj
    if isinstance(obj, list):
        return [_fold_obj(x, ctx) for x in obj]
    if isinstance(obj, dict):
        return {k: _fold_obj(v, ctx) for k, v in obj.items()}
    return obj


# --------------------------------------------------------------------------- #
# 内容块截断
# --------------------------------------------------------------------------- #

def _truncate_tool_use(block: dict, ctx: _Ctx) -> dict:
    """tool_use：保留工具名，参数序列化 >truncate_bytes 则截断为 preview + 原始长度。"""
    if "input" not in block:
        return block
    inp = block["input"]
    if inp is None:
        return block
    canonical = json.dumps(inp, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(canonical.encode("utf-8")) <= ctx.truncate_bytes:
        return block
    kept, _removed, orig = _byte_truncate(canonical, ctx.truncate_bytes)
    ctx.truncated_records += 1
    new_block = dict(block)
    new_block["input"] = {
        "__lean_truncated__": True,
        "original_bytes": orig,
        "preview": kept,
    }
    return new_block


def _truncate_tool_result(block: dict, ctx: _Ctx) -> dict:
    """tool_result：内容 >truncate_bytes 则截首 2KB preview + 原始长度 + **被截部分 sha256**。

    sha256 计算于**脱敏前**的被截原文（凭 hash 可去冷层核对完整原文；hash 非密钥、可入 git）。
    preview 随后仍过全局脱敏，故截断残块内的密钥不会逃逸。
    """
    if "content" not in block:
        return block
    content = block["content"]
    if isinstance(content, str):
        canonical = content
    else:
        canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(canonical.encode("utf-8")) <= ctx.truncate_bytes:
        return block
    kept, removed, orig = _byte_truncate(canonical, ctx.truncate_bytes)
    sha = hashlib.sha256(removed.encode("utf-8")).hexdigest()
    ctx.truncated_records += 1
    new_block = dict(block)
    new_block["content"] = {
        "__lean_truncated__": True,
        "original_bytes": orig,
        "preview": kept,
        "sha256": sha,
    }
    return new_block


def _transform_block(block, ctx: _Ctx):
    if not isinstance(block, dict):
        return block
    bt = block.get("type")
    if bt in NOISE_BLOCK_TYPES:
        return None
    if bt == "tool_use":
        return _truncate_tool_use(block, ctx)
    if bt == "tool_result":
        return _truncate_tool_result(block, ctx)
    return block  # text / thinking / 其余：保留


def _transform_line(obj, ctx: _Ctx):
    """结构变换：噪声行丢弃 / message.content 内块截断 / 噪声块丢弃。返回 None=整行丢弃。

    信封字段与非 message 结构原样透传（后续 fold + redact 全局 pass 再处理其字符串值）。
    """
    if not isinstance(obj, dict):
        return obj
    if obj.get("type") in NOISE_LINE_TYPES:
        return None
    msg = obj.get("message")
    if isinstance(msg, dict) and isinstance(msg.get("content"), list):
        new_blocks = []
        for block in msg["content"]:
            nb = _transform_block(block, ctx)
            if nb is not None:
                new_blocks.append(nb)
        new_msg = dict(msg)
        new_msg["content"] = new_blocks
        obj = dict(obj)
        obj["message"] = new_msg
    return obj


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #

def lean_transform(
    raw_lines: Iterable[str],
    denylist: DenylistResult | None = None,
    truncate_bytes: int = DEFAULT_TRUNCATE_BYTES,
) -> LeanResult:
    """对单会话 raw JSONL 行流做 lean 变换 + secret 脱敏，输出确定性 lean 行流。

    确定性：同输入 → 逐字节相同输出（无时间戳 / 随机 / 无序遍历入输出）。
    首行=元数据头（schema + REDACTED 分类型计数 + 截断记录数 + 折叠数），其后为 lean JSON 行。
    被截 tool_result 行内联记 原始长度 + 被截部分 sha256。

    负控（AC-2·扫描器非惰性）说明：本函数无“关闭脱敏”开关（护冻结签名）；负控由 T7 直接对
    **raw fixture 行**跑 ``hard_gate_scan`` 得命中 >0 达成，正控则对本函数 lean 产物跑得 =0。
    """
    ctx = _Ctx(truncate_bytes=truncate_bytes, denylist=denylist)
    out_lines: list[str] = []
    warnings: list[str] = []

    for idx, raw in enumerate(raw_lines, 1):
        if raw is None:
            continue
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError) as exc:
            # 非法 / 尾部不完整行：保留脱敏后原文并 warning（不静默丢证据）。
            warnings.append(f"line {idx}: invalid JSON ({exc}); kept raw with redaction")
            out_lines.append(_redact_string(line, ctx))
            continue
        transformed = _transform_line(obj, ctx)
        if transformed is None:
            continue  # 噪声行整行丢弃
        transformed = _fold_obj(transformed, ctx)
        transformed = _redact_obj(transformed, ctx)
        out_lines.append(
            json.dumps(transformed, ensure_ascii=False, separators=(",", ":"))
        )

    header = {
        "__lean_meta__": True,
        "schema": LEAN_SCHEMA,
        "redacted_counts": {k: ctx.counts[k] for k in sorted(ctx.counts) if ctx.counts[k] > 0},
        "truncated_records": ctx.truncated_records,
        "prompt_state_folded": ctx.prompt_state_folded,
    }
    header_line = json.dumps(header, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    # denylist 编译降级 / 长度护栏跳过 → 汇入 warnings（可观测）。
    if denylist is not None:
        for lineno, err in denylist.skipped:
            warnings.append(f"denylist line {lineno}: skipped ({err})")
    if ctx.denylist_guard_skips:
        warnings.append(
            f"denylist length guard skipped matching on {ctx.denylist_guard_skips} "
            f"oversized string(s) (> {DENYLIST_MAX_LINE_CHARS} chars; builtin family still applied)"
        )

    return LeanResult(lines=[header_line] + out_lines, warnings=warnings)


# --------------------------------------------------------------------------- #
# 第二检测器 · 硬门层（独立 ruleset 超集）
# --------------------------------------------------------------------------- #

def _mask(s: str) -> str:
    s = s.replace("\n", " ").replace("\r", " ")
    if len(s) <= 4:
        return "***"
    return f"{s[:4]}***(len={len(s)})"


def hard_gate_scan(
    lines: Iterable[str],
    allow_fingerprints: frozenset[str] = frozenset(),
) -> list[dict]:
    """硬门层扫描：用**独立维护的 secret ruleset 超集**逐行扫描（与脱敏族不同源）。

    每命中一 dict：``{rule, line_no, snippet, fingerprint}``（snippet 为脱敏化掩码片段，不回显
    原始密钥；fingerprint 为确定性单向指纹，见下）。正控：对脱敏后 lean 产物扫描应得 ``[]``；
    负控：对未脱敏 raw 扫描应得非空（扫描器非惰性）。

    参数
    ----
    allow_fingerprints:
        已审白名单指纹集（默认空集，既有单参调用零破坏）。凡命中的 ``fingerprint`` ∈ 本集的
        finding **从返回列表剔除**（人工审为伪命中后放行），其余照常返回（C-3 · UQ-1=B+C）。

    fingerprint = ``sha256(f"{rule}:{命中原文}").hexdigest()[:16]``——确定性、单向不可逆、
    非密钥回显（仅供 T3 fail-closed 时打印供人工审核、加入 config 白名单，下轮放行）。
    """
    findings: list[dict] = []
    for i, line in enumerate(lines, 1):
        text = line if isinstance(line, str) else str(line)
        for name, pat in HARD_GATE_RULES:
            for m in pat.finditer(text):
                hit = m.group(0)
                fingerprint = hashlib.sha256(f"{name}:{hit}".encode()).hexdigest()[:16]
                if fingerprint in allow_fingerprints:
                    continue  # 已审伪命中白名单放行，杜绝永久阻断归档（C-3 · AC-6）
                findings.append({
                    "rule": name,
                    "line_no": i,
                    "snippet": _mask(hit),
                    "fingerprint": fingerprint,
                })
    return findings


# --------------------------------------------------------------------------- #
# 第二检测器 · 告警层（高熵启发 + provenance 白名单）
# --------------------------------------------------------------------------- #

_ENTROPY_RUN_RE = re.compile(r"[A-Za-z0-9+/=_\-]{%d,}" % ENTROPY_MIN_RUN_LEN)


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    n = len(s)
    freq = Counter(s)
    return -sum((c / n) * log2(c / n) for c in freq.values())


def _high_entropy_runs(s: str):
    """产出 (run, entropy)：charset 连续段长度 >= 阈且 Shannon 熵 >= 阈值。"""
    for m in _ENTROPY_RUN_RE.finditer(s):
        run = m.group(0)
        ent = _shannon_entropy(run)
        if ent >= ENTROPY_THRESHOLD:
            yield run, ent


def _walk_strings(obj, parent_key, path, out):
    """深度遍历，收集 (紧邻字段键, JSON 路径, 字符串值)。list 元素继承其所在字段键。"""
    if isinstance(obj, str):
        out.append((parent_key, path, obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _walk_strings(v, k, f"{path}.{k}", out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk_strings(v, parent_key, f"{path}[{i}]", out)


def entropy_scan(lean_lines: Iterable[str]) -> list[dict]:
    """告警层扫描：高熵串启发，**按 JSON 字段位置 / provenance 消解良性高熵白名单**（C-3）。

    白名单**不按值形态匹配**：仅当高熵串所在**字段键** ∈ PROVENANCE_WHITELIST_KEYS（元数据头 /
    ``sha256`` / ``sessionId`` / git SHA 信封字段）时豁免；同形态高熵串若落在 ``text`` / ``content`` /
    ``thinking`` / ``preview`` / tool_use ``input`` 等**内容正文位置**照常告警。元数据头整行豁免。

    返回 list[dict]：``{kind:"entropy", line_no, path, entropy, length, snippet}``（snippet 掩码化）。
    """
    alerts: list[dict] = []
    for i, line in enumerate(lean_lines, 1):
        text = line if isinstance(line, str) else str(line)
        try:
            obj = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            # 非 JSON 行（如保留的非法原文）：按内容正文处理、无白名单豁免。
            for run, ent in _high_entropy_runs(text):
                alerts.append({
                    "kind": "entropy", "line_no": i, "path": "<raw>",
                    "entropy": round(ent, 4), "length": len(run), "snippet": _mask(run),
                })
            continue
        if isinstance(obj, dict) and obj.get("__lean_meta__") is True:
            continue  # lean 元数据头整行为归档产物 → 白名单豁免
        leaves: list[tuple] = []
        _walk_strings(obj, None, "$", leaves)
        for parent_key, path, s in leaves:
            if parent_key in PROVENANCE_WHITELIST_KEYS:
                continue  # provenance 白名单：按字段键位置豁免（非按值形态）
            for run, ent in _high_entropy_runs(s):
                alerts.append({
                    "kind": "entropy", "line_no": i, "path": path,
                    "entropy": round(ent, 4), "length": len(run), "snippet": _mask(run),
                })
    return alerts
