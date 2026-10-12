#!/usr/bin/env bash
# lib/shell-utils.sh —— Harness hook/脚本公共工具函数单点（TG-1 · 防内联复制漂移）。
#
# 抽取自三处内联复制（逐字保语义，行为零回归）：
#   - resolve_root  ← .claude/hooks/static_security_scan.sh（单根三层 fallback）
#                    ← .claude/hooks/user_prompt_state_inject.sh（同型单根三层）
#   - resolve_roots ← .claude/hooks/stop_progress_check.sh（多根四层 · 含 worktree 主仓兜底）
# 供这些 hook source 共享，单点化"自定位仓库根"口径。
#
# 设计纪律（同 lib/merged_detect.sh）：
#   - 纯函数库、无副作用、不修改任何文件、不 commit/push。
#   - 被 source；不强设 `set -e`——本 lib 仅定义函数，被 source 时不应改变调用方 shell 选项
#     （hook 须容错不中途中止、最终 exit 0；强加 -e 会破坏调用方的 exit 0 收尾纪律）。
#   - bash 3.2 兼容：不使用 declare -A / 关联数组 / mapfile / readarray。

# resolve_root —— 单根自定位（三层 fallback · 逐字同 static_security_scan.sh 原 resolve_root）：
#   1) git rev-parse --show-toplevel    → 当前 worktree 根
#   2) ${CLAUDE_PROJECT_DIR:-}           → Claude Code 注入
#   3) $PWD                              → 至少保证脚本本体可运行
# stdout 输出单个根路径；恒返回 0。
resolve_root() {
  local top
  top="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  if [ -n "$top" ]; then
    printf '%s\n' "$top"
    return 0
  fi
  if [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
    printf '%s\n' "$CLAUDE_PROJECT_DIR"
    return 0
  fi
  printf '%s\n' "$PWD"
}

# resolve_roots —— 多根自定位（四层 · 逐字同 stop_progress_check.sh 原 resolve_roots）：
#   1) git rev-parse --show-toplevel                   → 当前 worktree 根
#   2) 身在 git worktree 时再补主仓根 = dirname(git rev-parse --git-common-dir)
#      （仅当与当前根不同才输出 · 解决 failure-record-001-stop-hook-path）
#   3) git 不可用时回退 ${CLAUDE_PROJECT_DIR:-}
#   4) 最后回退 $PWD
# stdout 逐行输出一个或多个根路径；恒返回 0。
resolve_roots() {
  local top common common_abs main
  top="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  if [ -n "$top" ]; then
    printf '%s\n' "$top"
    common="$(git rev-parse --git-common-dir 2>/dev/null || true)"
    if [ -n "$common" ]; then
      common_abs="$(cd "$common" 2>/dev/null && pwd || true)"
      if [ -n "$common_abs" ]; then
        main="$(dirname "$common_abs")"
        if [ -n "$main" ] && [ "$main" != "$top" ]; then
          printf '%s\n' "$main"
        fi
      fi
    fi
    return 0
  fi
  if [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
    printf '%s\n' "$CLAUDE_PROJECT_DIR"
    return 0
  fi
  printf '%s\n' "$PWD"
}

# harness_state_root —— 会话内稳定的 STATE_DIR 根解析（方案甲 · 锚 CLAUDE_PROJECT_DIR · U-1）：
#   feat-segmentation-and-statedir-fix-20260714 · T-B · spec §5.1 U-1 裁决。
#   口径：git -C "${CLAUDE_PROJECT_DIR:-$PWD}" rev-parse --show-toplevel（族 B 读端既有口径）
#         → 失败回退 ${CLAUDE_PROJECT_DIR:-$PWD}。
#   为何锚 CLAUDE_PROJECT_DIR 而非 resolve_root()（裸 git rev-parse · 跟 cwd）：会话中途
#   EnterWorktree 改 cwd 时，裸 git rev-parse 漂到 worktree（族 A 写端 bug · spec §1.2），
#   而 CLAUDE_PROJECT_DIR 是会话起点项目根、不随 cwd 漂 → 读写落同一 STATE_DIR。
#   **不改 resolve_root() 本体**（它另供 .harness/changes 内容 / 契约注入源定位 · 跟 cwd 是其应然）。
#   本函数是 STATE_DIR 解析的**单一权威口径**；各 hook 若未 source 本 lib，内联兜底逐字复制本体
#   （与既有 resolve_root 内联兜底同家法 · 字节一致 · 防漂移）。
# stdout 输出单个根路径；恒返回 0。
harness_state_root() {
  local top
  top="$(git -C "${CLAUDE_PROJECT_DIR:-$PWD}" rev-parse --show-toplevel 2>/dev/null || true)"
  if [ -n "$top" ]; then
    printf '%s\n' "$top"
    return 0
  fi
  printf '%s\n' "${CLAUDE_PROJECT_DIR:-$PWD}"
}

# _harness_json_escape <str> —— 最小 JSON 字符串体转义（segment_handoff 写侧用）：
#   剔控制字符（换行/回车/制表）→ 反斜杠、双引号转义（保证单行 JSON 合法）。
#   顺序：先剔控制字符再转义（对齐 l_sanitize_scope 家法）。
_harness_json_escape() {
  printf '%s' "$1" | tr -d '\n\r\t' | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

# harness_write_segment_handoff —— T-A3 写侧极简入口（feat-segmentation-and-statedir-fix-20260714）：
#   Owner 在用户采纳分段建议时调用，落 $STATE_DIR/segment_handoff.json（跨会话交接 · 不带 sid）。
#   $1=目标卡目录（如 .harness/changes/<card>） $2=下一步阶段（如 3 / 7） $3=一句交接注。
#   STATE_DIR 走 harness_state_root() 统一口径（与 SessionStart 消费侧同源 · /clear 前后同目录）。
#   HARNESS_STATE_DIR 覆写语义保留。写成功返回 0；异常返回 1（Owner 可感知，但绝不 die）。
#   Owner 调用示例（source 本 lib 后一行调用）：
#     . <lib>/shell-utils.sh && harness_write_segment_handoff ".harness/changes/<card>" "3" "阶段2 已评审通过，续推编码"
harness_write_segment_handoff() {
  local root sdir f ts
  root="$(harness_state_root)"
  sdir="${HARNESS_STATE_DIR:-$root/.harness/state}"
  mkdir -p "$sdir" 2>/dev/null || return 1
  [ -f "$sdir/.gitignore" ] || printf '*\n' > "$sdir/.gitignore" 2>/dev/null || true
  ts="$(date '+%Y-%m-%dT%H:%M:%S%z' 2>/dev/null || true)"
  f="$sdir/segment_handoff.json"
  printf '{"target_card":"%s","next_stage":"%s","note":"%s","ts":"%s"}\n' \
    "$(_harness_json_escape "$1")" "$(_harness_json_escape "$2")" \
    "$(_harness_json_escape "$3")" "${ts:-unknown}" > "$f" 2>/dev/null || return 1
  return 0
}

# warn <msg> —— 统一 stderr warning 输出（不阻断 · 不改退出码）。
warn() { printf 'warning: %s\n' "$1" >&2; }

# die <msg> [code] —— stderr 报错并退出（默认码 1）。
# 注意：仅供"确需中止"的脚本调用；hook/维护脚本须容错不中止，勿用 die。
die() { printf 'error: %s\n' "$1" >&2; exit "${2:-1}"; }
