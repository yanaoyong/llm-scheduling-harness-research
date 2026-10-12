#!/usr/bin/env bash
# lib/merged_detect.sh —— FR-5「PR 已合并进 main」判定单点（INFO 采纳 · 防双源漂移）。
#
# 抽取自 session_start_autoflip.sh 原 FR-5 判定逻辑（行尾锚定 grep + from .../change/<dir> 二次
# 校验剔 re-sync + HEAD 祖先校验），供三处 source 共享：
#   - .claude/hooks/session_start_autoflip.sh（detect-only）
#   - .harness/scripts/list_flows.sh（--active 排除已合并卡）
#   - .harness/scripts/flip_merged.sh（显式翻牌落库）
#
# 设计纪律：
#   - 纯函数、无副作用、不修改任何文件、不 commit/push。
#   - bash 3.2 兼容：不使用 declare -A / 关联数组 / mapfile / readarray。
#   - 不强设 `set -e`（由调用方控）——本 lib 仅定义函数，被 source 时不应改变调用方 shell 选项。
#   - 调用方须先 cd 到仓库根（或保证 git 工作目录为目标仓），本函数不自定位仓库根。

# merged_detect_sha <card_dir>
#   判定变更目录 <card_dir>（如 chore-flip-summary-roadmap-20260617）对应的 PR 是否已以
#   merge commit 合并进 main 且为当前 HEAD 祖先。
#   命中 → stdout 输出 merge commit 短 SHA、返回 0；未命中 → 无输出、返回 1。
#   防子串假阳性（C-1）：行尾锚定 + from .../change/<dir>$ 词边界二次校验，杜绝
#   `chore-flip` 误匹配 `chore-flip-summary-roadmap`，并剔除 `Merge ... into change/<dir>`
#   形式的 branch 内 re-sync 合并（change/<dir> 是合并目的地非源分支）。
merged_detect_sha() {
  card_dir="$1"
  [ -n "$card_dir" ] || return 1

  # (1) 行尾锚定 grep 取候选 merge commit（BRE · $ 锚行尾；分支名仅 [a-z0-9-] 无元字符）
  _md_cand="$(git log main --merges --grep "change/$card_dir\$" --format='%H' 2>/dev/null || true)"
  [ -z "$_md_cand" ] && return 1

  # (2) 二次校验 + (3) 祖先校验：逐个候选取首个满足者。
  _md_merge=""
  for _md_c in $_md_cand; do
    _md_subj="$(git show -s --format=%s "$_md_c" 2>/dev/null || true)"
    printf '%s' "$_md_subj" | grep -Eq "from [^[:space:]]+/change/$card_dir\$" || continue
    git merge-base --is-ancestor "$_md_c" HEAD 2>/dev/null || continue
    _md_merge="$_md_c"
    break
  done
  [ -z "$_md_merge" ] && return 1

  _md_short="$(git rev-parse --short "$_md_merge" 2>/dev/null || true)"
  [ -z "$_md_short" ] && return 1

  printf '%s\n' "$_md_short"
  return 0
}
