#!/usr/bin/env bash
# lib/frontmatter.sh —— frontmatter（---…---）`status:` 解析单点（TG-1 · 防内联复制漂移）。
#
# 抽取自两处口径一致的内联复制（逐字保语义）：
#   - .harness/scripts/list_flows.sh          的 _fm_status()
#   - .claude/hooks/user_prompt_state_inject.sh 的 _eval_status()
# 两者均为"纯 awk 解析首个 frontmatter 块内 status: 值（去空格 · 小写）"，本 lib 收为单源。
# 消费方可在本地包一层别名（如 _eval_status / _fm_status）保持既有函数名兼容。
#
# 设计纪律（同 lib/merged_detect.sh / lib/shell-utils.sh）：
#   - 纯函数库、无副作用；被 source；不强设 `set -e`（不改变调用方 shell 选项）。
#   - bash 3.2 兼容：纯 awk 实现，无关联数组 / 无 jq / 无 bash4 语法。

# fm_status <file> —— 从 <file> 首个 frontmatter（---…---）区块内提取 `status:` 值，
#   去首尾空格、转小写后 print；缺失 / 无 frontmatter / 解析失败 → 空串（stdout 为空）。
fm_status() {
  awk '
    NR==1 && $0 !~ /^---[[:space:]]*$/ { exit }   # 无 frontmatter
    NR==1 { infm=1; next }
    infm && $0 ~ /^---[[:space:]]*$/ { exit }       # frontmatter 结束
    infm && $0 ~ /^[[:space:]]*status[[:space:]]*:/ {
      sub(/^[[:space:]]*status[[:space:]]*:[[:space:]]*/, "")
      sub(/[[:space:]]+$/, "")
      print tolower($0); exit
    }
  ' "$1" 2>/dev/null
}

# fm_is_resolved <file> —— status ∈ {resolved,closed,done} → 0（已闭合）；否则 1（计入 · 含缺失/open）。
fm_is_resolved() {
  case "$(fm_status "$1")" in
    resolved|closed|done) return 0 ;;
    *) return 1 ;;
  esac
}
