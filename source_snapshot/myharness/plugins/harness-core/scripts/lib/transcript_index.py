"""transcript_index — by-instance 索引核心库（T2 · feat-transcript-archive-20260717）。

纯 stdlib（Python 3.11+），零第三方依赖。从会话 **raw JSONL** 提取卡/实例关联并
生成幂等索引，覆盖三类：K 卡 / M 元流程实例（proj-*）/ 无实例会话。

关联提取（spec §2.1.5 冻结）：
  - 信号一：会话全部顶层信封字段 ``gitBranch`` 值；``change/<x>`` 形态 → K 卡实例名 ``<x>``。
  - 信号二：正则 ``\\.harness/changes/([^/]+)/`` 扫全部 tool_use 参数路径 → 实例名。
  - 两路并集。并集为空 → 无实例会话。
  - 实例类型按实例名逐个判定：``proj-`` 前缀 = M（元流程），其余 = K（卡）。

对外接口（Owner 冻结 · T3/T7 按此调用，签名不得偏离）：
  - ``extract_session_meta(raw_lines, project, session_id) -> dict``
  - ``render_index_tsv(metas) -> str``
  - ``render_by_instance(metas, lean_relpath) -> dict``

输出确定性是最高设计约束：排序固定、无时间戳/随机、同输入重跑逐字节不变。
raw JSONL 坏行（非 JSON）skip 不抛，保持库健壮。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable, Iterable

# --- 冻结常量（改动会破坏幂等/快照，须谨慎） ---------------------------------

# 信号二：tool_use 参数路径中的变更实例名捕获。
# 字符集收紧为合法卡名字符集（spec §2.3 C-2 · [A-Za-z0-9._-]+）——真实卡名
# （fix-…-20260717 / chore-… / proj-…）全落此集；杜绝 [^/]+ 吞下 transcript 内
# 含 .harness/changes/ 的命令文本碎片（空格/引号/换行）致污染实例名。
_CHANGES_RE = re.compile(r"\.harness/changes/([A-Za-z0-9._-]+)/")
# 信号一：change/<x> 分支 → K 卡实例名 <x>（同收紧字符集，防含其他字符的分支误捕）。
_CHANGE_BRANCH_RE = re.compile(r"^change/([A-Za-z0-9._-]+)$")
# M 元流程实例名前缀。
_META_PREFIX = "proj-"

# by-instance 落盘 slug 消毒上限与哈希后缀长度（spec §2.3 C-2 冻结值）。
# 上限 80 字符；超限 → 前 (80-1-12)=67 字符 + "-" + sha256(原始 name)[:12]。
SLUG_MAX = 80
SLUG_HASH_LEN = 12
# 消毒后为空时的安全占位（不得产出空文件名）。
SLUG_FALLBACK = "_invalid"
# slug 落盘允许字符集（与 _CHANGES_RE 捕获集一致）。
_SLUG_ILLEGAL_RE = re.compile(r"[^A-Za-z0-9._-]")

# index.tsv 集合列内部分隔符（排序后 join，保证确定性）。
SET_SEP = ","
# 首条 prompt 摘要单行化后的长度上限（自定常量）。
FIRST_PROMPT_MAX = 200
# 无实例会话归入的固定约定页名。
NO_INSTANCE_PAGE = "_no-instance"

# index.tsv 表头（冻结列名与列序，不得增删改）。
INDEX_HEADER = ["session", "日期", "项目", "分支集", "cards", "实例类型", "首条 prompt 摘要"]


# --- 内部工具 ---------------------------------------------------------------

def _iter_tool_use_inputs(obj: Any) -> Iterable[Any]:
    """递归遍历已解析行对象，产出所有 ``type == "tool_use"`` 块的 ``input`` 值。

    tool_use 块在 Claude Code JSONL 中通常位于 ``message.content`` 列表内，但为健壮
    起见对整棵对象树递归查找，不假设固定嵌套位置。
    """
    if isinstance(obj, dict):
        if obj.get("type") == "tool_use":
            inp = obj.get("input")
            if inp is not None:
                yield inp
        for value in obj.values():
            yield from _iter_tool_use_inputs(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_tool_use_inputs(item)


def _iter_strings(obj: Any) -> Iterable[str]:
    """递归产出对象树内所有字符串叶子（用于对 tool_use input 扫路径正则）。"""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _iter_strings(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_strings(item)


def _user_text(message: Any) -> str:
    """从 user 消息体提取纯文本；跳过 tool_result 等非文本块。"""
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _iso_date(timestamp: str) -> str:
    """ISO 8601 时间戳 → ``YYYY-MM-DD`` 日期部分（best effort）。"""
    return timestamp.split("T", 1)[0]


def _sanitize_summary(text: str) -> str:
    """单行化 + 去 tab/换行 + 折叠空白 + 截断到 FIRST_PROMPT_MAX。

    Python str 按码点切片，截断不会切出半个 UTF-8 码点。
    """
    text = text.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    text = " ".join(text.split())
    if len(text) > FIRST_PROMPT_MAX:
        text = text[:FIRST_PROMPT_MAX]
    return text


def _kind_of(instance_name: str) -> str:
    """实例名 → 类型：proj- 前缀 = M，其余 = K。"""
    return "M" if instance_name.startswith(_META_PREFIX) else "K"


def _sanitize_slug(name: str) -> str:
    """把实例名消毒为有界、确定性、可落盘的 by-instance 文件名 slug。

    落盘侧兜底（解析正则已收紧字符集，此为纵深防御，护住构造/历史脏数据）：
      1. 剥离非 ``[A-Za-z0-9._-]`` 字符。
      2. 剥离后为空 → 回退安全占位 ``SLUG_FALLBACK``，绝不产出空文件名。
      3. 长度 > ``SLUG_MAX``(80) → 取前 ``SLUG_MAX - 1 - SLUG_HASH_LEN``(=67) 字符
         + ``"-"`` + ``sha256(原始 name).hexdigest()[:SLUG_HASH_LEN]``(12)，合成
         定长 80 字符 slug，杜绝 ``OSError: File name too long``。

    确定性铁律：哈希对**原始 name** 串取（非消毒后串），同输入逐字节同输出，
    护 index/by-instance 幂等（本库首段声「输出确定性是最高设计约束」）。
    """
    cleaned = _SLUG_ILLEGAL_RE.sub("", name)
    if not cleaned:
        return SLUG_FALLBACK
    if len(cleaned) > SLUG_MAX:
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:SLUG_HASH_LEN]
        keep = SLUG_MAX - 1 - SLUG_HASH_LEN  # 80 - 1 - 12 = 67
        cleaned = cleaned[:keep] + "-" + digest
    return cleaned


# --- 对外接口（签名冻结） ---------------------------------------------------

def extract_session_meta(
    raw_lines: Iterable[str], project: str, session_id: str
) -> dict:
    """从单会话 raw JSONL 行流提取索引元数据。

    返回 dict（键冻结）::

        session / date（会话首条含 timestamp 行的日期 YYYY-MM-DD，无则空串）/
        project / branches（sorted list[str]）/ cards（sorted list[str] · 实例名并集）/
        instance_kinds（sorted list · 'K'/'M'/'none'）/ first_prompt_summary（str）。

    坏行（非 JSON / 非 dict）skip 不抛。
    """
    branches: set[str] = set()
    cards: set[str] = set()
    date = ""
    first_prompt = ""

    for raw in raw_lines:
        if not raw or not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except (ValueError, TypeError):
            # 坏行容忍：非 JSON 行 skip，不抛。
            continue
        if not isinstance(obj, dict):
            continue

        # date：首条含 timestamp 的信封行。
        if not date:
            ts = obj.get("timestamp")
            if isinstance(ts, str) and ts:
                date = _iso_date(ts)

        # 信号一：顶层信封字段 gitBranch。
        git_branch = obj.get("gitBranch")
        if isinstance(git_branch, str) and git_branch:
            branches.add(git_branch)
            m = _CHANGE_BRANCH_RE.match(git_branch)
            if m:
                cards.add(m.group(1))

        # 信号二：tool_use 参数路径。
        for inp in _iter_tool_use_inputs(obj):
            for text in _iter_strings(inp):
                for m in _CHANGES_RE.finditer(text):
                    cards.add(m.group(1))

        # 首条 prompt：第一条含文本的 user 消息。
        if not first_prompt and obj.get("type") == "user":
            message = obj.get("message", obj)
            text = _user_text(message)
            if text and text.strip():
                first_prompt = _sanitize_summary(text)

    kinds: set[str] = {_kind_of(card) for card in cards}
    if not kinds:
        kinds.add("none")

    return {
        "session": session_id,
        "date": date,
        "project": project,
        "branches": sorted(branches),
        "cards": sorted(cards),
        "instance_kinds": sorted(kinds),
        "first_prompt_summary": first_prompt,
    }


def render_index_tsv(metas: list[dict]) -> str:
    """全量渲染 index.tsv 内容（含表头行）。

    metas 按 session 排序后输出，确定性。集合列内部已 sorted，用 SET_SEP join。
    """
    lines = ["\t".join(INDEX_HEADER)]
    for meta in sorted(metas, key=lambda m: m.get("session", "")):
        row = [
            meta.get("session", ""),
            meta.get("date", ""),
            meta.get("project", ""),
            SET_SEP.join(meta.get("branches", [])),
            SET_SEP.join(meta.get("cards", [])),
            SET_SEP.join(meta.get("instance_kinds", [])),
            _sanitize_summary(meta.get("first_prompt_summary", "")),
        ]
        lines.append("\t".join(row))
    return "\n".join(lines) + "\n"


def render_by_instance(
    metas: list[dict], lean_relpath: Callable[[dict], str]
) -> dict[str, str]:
    """渲染 by-instance 归档侧权威页。

    返回 ``{相对路径: 文件内容}``，键形如 ``by-instance/<project>/<实例名>.md``；
    无实例会话归入 ``by-instance/<project>/_no-instance.md``。确定性（全量重建、页内
    会话按 session 排序、无时间戳）。
    """
    # key -> set[(session, date, lean)]，用 set 去重同会话重复关联。
    pages: dict[str, set[tuple[str, str, str]]] = {}
    # key -> (project, 展示名, kind)。
    page_meta: dict[str, tuple[str, str, str]] = {}

    for meta in metas:
        project = meta.get("project", "")
        cards = meta.get("cards") or []
        row = (meta.get("session", ""), meta.get("date", ""), lean_relpath(meta))
        if cards:
            for card in cards:
                # 文件名用消毒后 slug（有界/确定性/可落盘）；页内展示名保留原始 card。
                slug = _sanitize_slug(card)
                key = f"by-instance/{project}/{slug}.md"
                pages.setdefault(key, set()).add(row)
                page_meta[key] = (project, card, _kind_of(card))
        else:
            key = f"by-instance/{project}/{NO_INSTANCE_PAGE}.md"
            pages.setdefault(key, set()).add(row)
            page_meta[key] = (project, NO_INSTANCE_PAGE, "none")

    out: dict[str, str] = {}
    for key in sorted(pages):
        project, name, kind = page_meta[key]
        rows = sorted(pages[key])
        lines = [
            f"# by-instance · {name}",
            "",
            f"- project: {project}",
            f"- kind: {kind}",
            f"- sessions: {len(rows)}",
            "",
            "| session | date | lean |",
            "|---|---|---|",
        ]
        for session, date, lean in rows:
            lines.append(f"| {session} | {date} | {lean} |")
        lines.append("")
        out[key] = "\n".join(lines)
    return out
