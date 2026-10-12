#!/usr/bin/env bash
# lib/mirror_sync_lib.sh — 镜像分层刷新引擎（fix-mirror-upgrade-propagation-20260714 · T2/T4/T5/T6/T7）。
#
# 被 hooks/session_start_mirror_sync.sh source（宿主 · T8），也可被 pytest 直接 source 做单元断言。
# 权威源 base 解析：本仓 plugins/harness-core/ 优先 → $CLAUDE_PLUGIN_ROOT（NS-1 · version 读取与内容拷贝同 base）。
#
# 设计纪律：
#   - 纯函数库、被 source；不强设 set -e（调用方 hook 须容错、最终 exit 0）。
#   - bash 3.2 兼容：无 declare -A / 关联数组 / mapfile / readarray。
#   - 状态文件（版本戳 / 哈希台账 / 冲突报告 / 并发哨兵）一律经 harness_state_root() 落 STATE_DIR，
#     写入一律「临时文件 + 原子 rename」（FR-6 · AC-12 · statedir 跨项目泄漏教训）。
#   - 机制不读写任何 API key（AC-10）。
#   - stderr 统一前缀 [mirror-sync]；任何路径不 die（调用方保证 exit 0）。

MIRROR_SYNC_PREFIX="[mirror-sync]"

# 台账 schema 版本 sentinel（FR-8 · 字面量冻结 · 首行 # 注释行 · 条目行仍 key\thash）。
# 读侧字符串等值判定：台账首行 != 本字面量（含缺失）即视为旧 schema（旧全文件哈希口径）。
MIRROR_SYNC_LEDGER_SENTINEL="#ledger-schema=2-canonical"

# ── STATE_DIR 根解析单一口径（内联兜底逐字同 lib/shell-utils.sh · 未 source shell-utils 时可用）──
if ! type harness_state_root >/dev/null 2>&1; then
  harness_state_root() {
    local top
    top="$(git -C "${CLAUDE_PROJECT_DIR:-$PWD}" rev-parse --show-toplevel 2>/dev/null || true)"
    if [ -n "$top" ]; then
      printf '%s\n' "$top"
      return 0
    fi
    printf '%s\n' "${CLAUDE_PROJECT_DIR:-$PWD}"
  }
fi

mirror_sync_state_dir() {
  # echoes STATE_DIR（HARNESS_STATE_DIR 覆写优先 · 否则 harness_state_root()/.harness/state）
  local root
  root="$(harness_state_root)"
  printf '%s\n' "${HARNESS_STATE_DIR:-$root/.harness/state}"
}

# ── 权威源 base 解析（NS-1 · version 与 content 同 base）──
mirror_sync_resolve_base() {
  # $1 = TOP（git 仓库根）；echoes base（含 .claude-plugin/plugin.json 的目录），无则空
  local top="$1"
  if [ -f "$top/plugins/harness-core/.claude-plugin/plugin.json" ]; then
    printf '%s\n' "$top/plugins/harness-core"          # 本仓开发态（自托管）
  elif [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -f "${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json" ]; then
    printf '%s\n' "${CLAUDE_PLUGIN_ROOT}"              # 消费方 plugin 缓存安装态
  fi
}

# ── 版本读取（plugin.json version · 词法 grep/sed · 无 jq · AC-10 不触密钥）──
mirror_sync_read_version() {
  # $1 = base；echoes version 字符串
  local pj="$1/.claude-plugin/plugin.json"
  [ -r "$pj" ] || return 1
  grep -o '"version"[[:space:]]*:[[:space:]]*"[^"]*"' "$pj" 2>/dev/null | head -1 \
    | sed -E 's/.*"version"[[:space:]]*:[[:space:]]*"//; s/"$//'
}

# ── 版本戳读写（commit-last 契约的写侧 · 原子 temp+rename）──
mirror_sync_read_stamp() {
  # $1 = state_dir；echoes 已存版本戳（version 行 · 无则空 · 缺席不告警）
  local f="$1/mirror_sync_version_stamp"
  [ -r "$f" ] || return 0
  head -1 "$f" 2>/dev/null
}

mirror_sync_write_stamp() {
  # $1 = state_dir；$2 = version；原子 temp+rename；成功 0 失败 1
  local sdir="$1" ver="$2" tmp
  mkdir -p "$sdir" 2>/dev/null || return 1
  [ -f "$sdir/.gitignore" ] || printf '*\n' > "$sdir/.gitignore" 2>/dev/null || true
  tmp="$(mktemp "$sdir/.mirror_stamp.XXXXXX" 2>/dev/null)" || return 1
  printf '%s\n' "$ver" > "$tmp" 2>/dev/null || { rm -f "$tmp" 2>/dev/null; return 1; }
  mv -f "$tmp" "$sdir/mirror_sync_version_stamp" 2>/dev/null || { rm -f "$tmp" 2>/dev/null; return 1; }
  return 0
}

# ── 内容哈希（sha256 优先 · 缺失回退 cksum · 恒有稳定输出防 torn-read 误判）──
mirror_sync_hash() {
  # $1 = 文件；echoes 稳定哈希（不可读/缺失 → 空）
  [ -r "$1" ] || return 0
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" 2>/dev/null | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" 2>/dev/null | awk '{print $1}'
  else
    cksum "$1" 2>/dev/null | awk '{print $1"-"$2}'
  fi
}

# ── canonical 哈希口径（FR-1 · 缺陷② 改1 · NG-6 上层包装 · 底层 mirror_sync_hash 回退链不动）──
_mirror_hash_stdin() {
  # 从 stdin 取稳定哈希（回退链同 mirror_sync_hash · 上层管道包装 · 不落中间临时文件）
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum 2>/dev/null | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 2>/dev/null | awk '{print $1}'
  else
    cksum 2>/dev/null | awk '{print $1"-"$2}'
  fi
}

mirror_sync_canonical_hash() {
  # $1 = 文件；echoes canonical 哈希（记录口径 == 比对口径 · FR-1）：
  #   含 HARNESS:IDENTITY:START/END 标记的文件 → 剔除标记块之间内容后哈希（身份段机器再生不制造假"本地改动"）；
  #   无标记块 → 退化为整文件哈希（mirror_sync_hash · 零回归 · AC-1）。
  # 防御（阶段4 评审 S1）：含 START 但**无匹配 END** 的损坏文件 → awk 剔块会"无限吞"START 后全部内容
  #   （损坏 semi 件 + START 后本地手改会被误判未改而 clobber）→ 保守回退整文件哈希
  #   （任何差异都可见 · 宁误保护不误覆盖）。良构块行为零变化。
  # 不可读/缺失 → 空（同 mirror_sync_hash 语义）。管道式实现、不落中间临时文件（AC-11）。
  [ -r "$1" ] || return 0
  if _mirror_has_identity "$1" && grep -q "HARNESS:IDENTITY:END" "$1" 2>/dev/null; then
    awk '
      /HARNESS:IDENTITY:START/ { print; _ms_skip=1; next }
      /HARNESS:IDENTITY:END/   { _ms_skip=0; print; next }
      _ms_skip { next }
      { print }
    ' "$1" 2>/dev/null | _mirror_hash_stdin
  else
    mirror_sync_hash "$1"
  fi
}

# ── manifest 分类（FR-2 · custom 恒胜 + 最长匹配 · opt-out → skip）──
mirror_sync_classify() {
  # $1 = manifest 文件；$2 = 权威源根相对路径
  # echoes 生效动作：machine | semi | custom | skip | unclassified
  local mf="$1" path="$2" line class glob flag len
  local best_action="" best_len=-1 custom_hit=0
  [ -r "$mf" ] || { printf 'unclassified\n'; return 0; }
  while IFS= read -r line; do
    case "$line" in ''|'#'*) continue ;; esac
    # read -r 分词：天然不做 glob 展开（避宿主 cwd pathname expansion 撞名致泛 glob 退化）、
    # 作用域局部、bash 3.2 兼容；manifest 行最多 3 字段，多余尾字段被 flag 吸收，语义等价 set -- 分词。
    read -r class glob flag <<< "$line"
    [ -n "$glob" ] || continue
    case "$path" in
      $glob)
        if [ "$class" = "custom" ]; then
          custom_hit=1
        else
          len=${#glob}
          if [ "$len" -gt "$best_len" ]; then
            best_len="$len"
            if [ "$flag" = "opt-out" ]; then best_action="skip"; else best_action="$class"; fi
          fi
        fi
        ;;
    esac
  done < "$mf"
  if [ "$custom_hit" = "1" ]; then printf 'custom\n'; return 0; fi
  if [ -n "$best_action" ]; then printf '%s\n' "$best_action"; return 0; fi
  printf 'unclassified\n'
}

# ── 扫描根导出（从 manifest glob 推导需遍历的权威源子树 · manifest 单源）──
mirror_sync_scan_roots() {
  # $1 = manifest；echoes 去重后的顶层子树前缀（如 components scripts rules agents ...）
  local mf="$1" line glob root out=""
  [ -r "$mf" ] || return 0
  while IFS= read -r line; do
    case "$line" in ''|'#'*) continue ;; esac
    # read -r 分词：同 classify，避宿主 cwd glob 展开撞名致泛 glob 退化（class/flag 字段丢弃）。
    read -r _ glob _ <<< "$line"
    [ -n "$glob" ] || continue
    case "$glob" in
      *'*'*) root="${glob%%\**}"; root="${root%/}" ;;   # 取首个 * 前的目录段
      *)     root="$(dirname "$glob")" ;;               # 精确文件 → 其目录
    esac
    [ -n "$root" ] && [ "$root" != "." ] || continue
    case " $out " in *" $root "*) ;; *) out="$out $root" ;; esac
  done < "$mf"
  # shellcheck disable=SC2086
  printf '%s\n' $out
}

# ── 镜像落点映射（权威源根相对 → 镜像根相对 · _template/_TEMPLATE 例外）──
mirror_sync_dest_rel() {
  case "$1" in
    _template/_TEMPLATE/*) printf 'changes/_TEMPLATE/%s\n' "${1#_template/_TEMPLATE/}" ;;
    *) printf '%s\n' "$1" ;;
  esac
}

# ── 台账查值 ──
_mirror_ledger_lookup() {
  # $1 = ledger 文件；$2 = key；echoes hash（无则空）
  local ledger="$1" key="$2"
  [ -f "$ledger" ] || return 0
  awk -F '\t' -v k="$key" '$1==k{print $2; exit}' "$ledger" 2>/dev/null
}

_mirror_record_current() {
  # $1 = 镜像文件；$2 = ledger key；$3 = 新台账（追加）——记录镜像文件 canonical 哈希
  # （FR-1 · 记录口径 == 比对口径 · 身份段机器再生不改变基线）
  local dest="$1" key="$2" newl="$3" h=""
  [ -f "$dest" ] && h="$(mirror_sync_canonical_hash "$dest")"
  printf '%s\t%s\n' "$key" "${h:-NA}" >> "$newl" 2>/dev/null || true
}

# ── 并发守卫 ──
_mirror_bootstrap_live() {
  # $1 = state_dir；.bootstrap_running 内含活 pid → 0（NS-2 双写窗口检测）
  local f="$1/.bootstrap_running" pid
  [ -f "$f" ] || return 1
  pid="$(head -1 "$f" 2>/dev/null | tr -cd '0-9')"
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null
}

mirror_sync_lock_acquire() {
  # $1 = state_dir；自锁防两会话并发全量刷新（fail-open · last-writer-wins 可容忍）；获锁 0 / 应让路 1
  local f="$1/.mirror_sync_running" pid
  if [ -f "$f" ]; then
    pid="$(head -1 "$f" 2>/dev/null | tr -cd '0-9')"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      return 1
    fi
  fi
  mkdir -p "$1" 2>/dev/null || return 0
  echo "$$" > "$f" 2>/dev/null || true
  return 0
}
mirror_sync_lock_release() { rm -f "$1/.mirror_sync_running" 2>/dev/null || true; }

# ── init_identity 定位（权威源 scripts/init_identity.sh）──
_mirror_locate_init_identity() {
  # 使用 run 期设置的 _MS_BASE
  if [ -n "${_MS_BASE:-}" ] && [ -r "${_MS_BASE}/scripts/init_identity.sh" ]; then
    printf '%s\n' "${_MS_BASE}/scripts/init_identity.sh"
    return 0
  fi
  return 1
}

_mirror_has_identity() {
  grep -q "HARNESS:IDENTITY:START" "$1" 2>/dev/null
}

# ── 半定制件身份回填（T5 · 临时文件 → 回填成功 → 原子 mv · 失败保留原文件）──
_mirror_semi_backfill() {
  # $1 = 权威源文件（src）；$2 = 镜像目标（dest）；$3 = 冲突报告文件
  # 成功 0；失败 1（保留原 dest 不动）
  local src="$1" dest="$2" creport="$3" tmp ii
  tmp="$(mktemp "${TMPDIR:-/tmp}/mirror_semi.XXXXXX" 2>/dev/null)" || { echo "semi-mktemp-failed: $dest" >> "$creport"; return 1; }
  if ! cp -p "$src" "$tmp" 2>/dev/null; then
    rm -f "$tmp" 2>/dev/null; echo "semi-cp-tmp-failed: $dest" >> "$creport"; return 1
  fi
  ii="$(_mirror_locate_init_identity || true)"
  if [ -z "$ii" ]; then
    rm -f "$tmp" 2>/dev/null; echo "semi-init-identity-missing: $dest" >> "$creport"; return 1
  fi
  # 对临时文件回填身份段（--target 显式禁回落默认候选 · 防呆禁权威源路径）
  if bash "$ii" --target "$tmp" >/dev/null 2>&1; then
    mkdir -p "$(dirname "$dest")" 2>/dev/null
    if mv -f "$tmp" "$dest" 2>/dev/null; then return 0; fi
    rm -f "$tmp" 2>/dev/null; echo "semi-mv-failed: $dest" >> "$creport"; return 1
  fi
  rm -f "$tmp" 2>/dev/null
  # 失败归因细分（AC-4.1）：回填失败最常见根因 = 消费方仓库根缺 HARNESS_CONFIG.yaml（init_identity exit 1）。
  # 与 init_identity 同口径解析仓库根 config（git 顶层，回落 PWD），缺失则写可行动提示、区别于其它失败态。
  local _cfg_top _cfg
  _cfg_top="$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")"
  _cfg="$_cfg_top/HARNESS_CONFIG.yaml"
  if [ ! -f "$_cfg" ]; then
    echo "semi-backfill-failed-config-missing: $dest（创建仓库根 HARNESS_CONFIG.yaml（可从 HARNESS_CONFIG.yaml.template 复制）后下次会话自动回填）" >> "$creport"
  else
    echo "semi-backfill-failed: $dest" >> "$creport"
  fi
  return 1
}

# ── 机器件/半定制件覆盖（T4/T5 · 台账本地改动保护 · 幂等）──
_mirror_apply_overwrite() {
  # $1=权威源文件(f) $2=权威源根相对(rel) $3=action(machine|semi) $4=镜像根 $5=old_ledger $6=new_ledger $7=creport
  #
  # 判定链严格定死（spec §4 顶部 · 缺陷② 三改 + FR-8 迁移互不抵消依赖此顺序）：
  #   ① src 可读性检查
  #   ② identical-to-源 canonical 短路（FR-3 · 不依赖台账提交时序 → 消双轮撕裂误标 + 粘性保护逃逸）
  #   ③ 保护比对（canonical 口径 · FR-1；命中记旧基线 led 跳过 · FR-2 粘性；
  #      FR-8 迁移判定内嵌本步入口：旧 schema 台账 ∧ 该文件〔dest∨src〕含 IDENTITY 标记 → led 不作可信基线）
  #   ④ 覆盖（记 canonical 基线）
  local f="$1" rel="$2" action="$3" mirror_root="$4" oldl="$5" newl="$6" creport="$7"
  local key dest cur led migrating
  key="$(mirror_sync_dest_rel "$rel")"
  dest="$mirror_root/$key"

  # ① src 可读性
  if [ ! -r "$f" ]; then
    MIRROR_SYNC_FAILED=1
    echo "src-unreadable: $rel" >> "$creport"
    _mirror_record_current "$dest" "$key" "$newl"
    return
  fi

  # ② identical-to-源 canonical 短路：镜像现内容（canonical）已 == 权威源（canonical）→ 已是权威新态
  #    → 记 canonical 基线、直接返回（不进保护分支、不重复 cp · 保幂等零写入）。
  #    不依赖台账时序：dest↔源直比，从根消除双轮撕裂窗口误标（FR-3）；同时为 FR-2 粘性保护提供逃逸
  #    （用户把本地文件改成与权威源一致 → 下轮此处命中 · 自动重记基线解除保护）。
  if [ -f "$dest" ] && [ "$(mirror_sync_canonical_hash "$dest")" = "$(mirror_sync_canonical_hash "$f")" ]; then
    _mirror_record_current "$dest" "$key" "$newl"
    return
  fi

  # ③ 保护比对（canonical 口径 · FR-1/FR-2 · FR-8 迁移判定内嵌）
  if [ -f "$dest" ]; then
    cur="$(mirror_sync_canonical_hash "$dest")"
    led="$(_mirror_ledger_lookup "$oldl" "$key")"
    # FR-8(2) 迁移判定（v3 判别收窄 · MF-2 方案 A）：旧 schema 台账（_MS_OLD_SCHEMA=1）
    # 且 该文件（dest∨src 保守判 · 复用 _mirror_has_identity）含 IDENTITY 标记 →
    # 其旧口径全文件哈希含身份段字节、与 canonical 不可比 → led 不作可信基线（视为该 key 尚无 canonical 基线）。
    # 无标记文件旧口径 == canonical 完全可比 → led 照常可信、走常规粘性保护语义。
    migrating=0
    if [ "${_MS_OLD_SCHEMA:-0}" = "1" ] && { _mirror_has_identity "$dest" || _mirror_has_identity "$f"; }; then
      migrating=1
    fi
    if [ "$migrating" = "0" ] && [ -n "$led" ] && [ -n "$cur" ] && [ "$cur" != "$led" ]; then
      # FR-2 粘性保护：本地改动 → 不覆盖、记旧台账基线 led（非当前 cur · 与 L364-366 components 让路 _dled 同构）
      # → 保护持续生效直至文件与权威源 canonical 一致（②短路自动解除）或人工清除台账条目。
      echo "local-modified-skip: $key（本地改动 · 粘性保护 · 保留基线 · 权威源较新未覆盖 · 改成与权威源一致 或 人工清除台账条目以接受升级）" >> "$creport"
      printf '%s\t%s\n' "$key" "$led" >> "$newl" 2>/dev/null || true
      return
    fi
    if [ "$migrating" = "1" ]; then
      # FR-8(3) 迁移轮以权威源覆盖 dest ≠ 源的 IDENTITY 件（未②短路即 canonical 有别）→ 留痕（宁留痕不静默 · R-9）
      echo "ledger-schema-migrated: $key" >> "$creport"
    fi
  fi

  # ④ 覆盖（记 canonical 基线）——到此 canonical 必有别（否则②已短路），恒需覆盖
  mkdir -p "$(dirname "$dest")" 2>/dev/null
  if [ "$action" = "semi" ] && _mirror_has_identity "$f"; then
    if ! _mirror_semi_backfill "$f" "$dest" "$creport"; then
      MIRROR_SYNC_FAILED=1
      _mirror_record_current "$dest" "$key" "$newl"
      return
    fi
  else
    if ! cp -p "$f" "$dest" 2>/dev/null; then
      MIRROR_SYNC_FAILED=1
      echo "cp-failed: $key" >> "$creport"
      _mirror_record_current "$dest" "$key" "$newl"
      return
    fi
  fi
  _mirror_record_current "$dest" "$key" "$newl"
}

# ── 定制件（T6 · 永不覆盖 · 上游模板变化 → 级联评估提示）──
_mirror_apply_custom() {
  # $1=权威源文件(f) $2=权威源根相对(rel) $3=TOP $4=old_ledger $5=new_ledger $6=creport
  local f="$1" rel="$2" top="$3" oldl="$4" newl="$5" creport="$6"
  local key="custom:$rel" auth_hash led
  auth_hash="$(mirror_sync_hash "$f")"
  led="$(_mirror_ledger_lookup "$oldl" "$key")"
  # 冷启动（led 空）：记基线、不 emit（UQ-4 定制件首建不覆盖但记基线）
  if [ -n "$led" ] && [ -n "$auth_hash" ] && [ "$led" != "$auth_hash" ]; then
    _mirror_emit_cascade "$top" "$rel" "$creport"
  fi
  printf '%s\t%s\n' "$key" "${auth_hash:-NA}" >> "$newl" 2>/dev/null || true
}

_mirror_emit_cascade() {
  # $1=TOP $2=定制件权威源根相对路径 $3=creport
  # 写「待处理级联评估」eval 报告文件到 proj-* 通道（user_prompt_state_inject.sh emit_cascade_section 既有 glob 消费）
  local top="$1" rule="$2" creport="$3" dir f safe
  dir="$top/.harness/changes/proj-mirror-sync-cascade/cascade_evaluations"
  mkdir -p "$dir" 2>/dev/null || { echo "cascade-mkdir-failed: $rule" >> "$creport"; return 0; }
  safe="$(printf '%s' "$rule" | tr '/ .' '___')"
  f="$dir/eval_${safe}.md"
  {
    printf -- '---\n'
    printf 'status: open\n'
    printf 'trigger: mirror-sync 定制件上游模板变化\n'
    printf 'rule: %s\n' "$rule"
    printf 'eval_date: %s\n' "$(date -u +%Y-%m-%d 2>/dev/null || echo unknown)"
    printf -- '---\n\n'
    printf '# 待处理级联评估 · 定制件上游模板变化\n\n'
    printf '定制规则 `%s` 的权威源模板已变化（mirror-sync 检测 · 版本升级传导）。\n\n' "$rule"
    printf -- '- 本定制件**未被自动覆盖**（custom 永不覆盖策略）。\n'
    printf -- '- 请人工评估：是否需要把上游模板变更级联到本地定制版本；评估后把本文件 frontmatter `status` 改为 `resolved`。\n'
  } > "$f" 2>/dev/null || { echo "cascade-write-failed: $rule" >> "$creport"; return 0; }
  echo "cascade-emitted: $rule（待处理级联评估已产出 → $f）" >> "$creport"
}

# ── 刷新主驱动（T4/T5/T6/T7 编排 · commit-last 判据由 hook 消费全局量）──
# 全局输出（hook 读）：MIRROR_SYNC_FAILED（非预期失败=1）、MIRROR_SYNC_DEFERRED（components 让路=1）
mirror_sync_run() {
  # $1=TOP $2=BASE $3=STATE_DIR $4=MANIFEST
  local top="$1" base="$2" sdir="$3" manifest="$4"
  local mirror_root="$top/.harness"
  MIRROR_SYNC_FAILED=0
  MIRROR_SYNC_DEFERRED=0
  _MS_BASE="$base"

  mkdir -p "$sdir" 2>/dev/null || { MIRROR_SYNC_FAILED=1; return 1; }
  [ -f "$sdir/.gitignore" ] || printf '*\n' > "$sdir/.gitignore" 2>/dev/null || true
  local old_ledger="$sdir/mirror_sync_hash_ledger"
  local new_ledger
  new_ledger="$(mktemp "$sdir/.mirror_ledger.XXXXXX" 2>/dev/null)" || { MIRROR_SYNC_FAILED=1; return 1; }

  # FR-8(1) 写侧：新台账首行写 schema 版本 sentinel（mktemp 建 temp 后、任何条目追加前立即写 · SH-5 位序定死）。
  printf '%s\n' "$MIRROR_SYNC_LEDGER_SENTINEL" > "$new_ledger" 2>/dev/null || true

  # FR-8(2) 读侧：判定旧台账 schema（字符串等值 · 首行 != 当前 sentinel〔含缺失〕即旧 schema · 免数值解析）。
  # 旧 schema 下 IDENTITY 件旧口径不可比 → _mirror_apply_overwrite 迁移判定（③）消费本全局量。
  local _old_first=""
  [ -f "$old_ledger" ] && _old_first="$(head -1 "$old_ledger" 2>/dev/null)"
  if [ "$_old_first" = "$MIRROR_SYNC_LEDGER_SENTINEL" ]; then
    _MS_OLD_SCHEMA=0
  else
    _MS_OLD_SCHEMA=1
  fi

  local conflict_report="$sdir/mirror_sync_conflicts.log"
  : > "$conflict_report" 2>/dev/null || true

  local bootstrap_running=0
  _mirror_bootstrap_live "$sdir" && bootstrap_running=1

  local root src_dir f rel action _dkey _dled
  for root in $(mirror_sync_scan_roots "$manifest"); do
    src_dir="$base/$root"
    [ -d "$src_dir" ] || continue
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      rel="${f#$base/}"
      action="$(mirror_sync_classify "$manifest" "$rel")"
      case "$action" in
        machine|semi)
          # NS-2：bootstrap 活 pid 时 components 类让路（跳过该类、下会话补齐、阻 commit-last）。
          # LOW-1（阶段4 评审）：让路时把旧台账中该文件基线条目**原样复制**进新台账——
          # 保基线不动（勿记当前磁盘态：让路窗口内磁盘可能正被 bootstrap 写一半），
          # 防 deferred 周期丢 component 基线 → 下一轮本地改动走无保护覆盖被 clobber。
          case "$rel" in
            components/*)
              if [ "$bootstrap_running" = "1" ]; then
                MIRROR_SYNC_DEFERRED=1
                echo "defer-components(bootstrap-running): $rel" >> "$conflict_report"
                _dkey="$(mirror_sync_dest_rel "$rel")"
                _dled="$(_mirror_ledger_lookup "$old_ledger" "$_dkey")"
                if [ -n "$_dled" ]; then
                  printf '%s\t%s\n' "$_dkey" "$_dled" >> "$new_ledger" 2>/dev/null || true
                fi
                continue
              fi
              ;;
          esac
          _mirror_apply_overwrite "$f" "$rel" "$action" "$mirror_root" "$old_ledger" "$new_ledger" "$conflict_report"
          ;;
        custom)
          _mirror_apply_custom "$f" "$rel" "$top" "$old_ledger" "$new_ledger" "$conflict_report"
          ;;
        *) : ;;   # skip（opt-out）/ unclassified → 不动
      esac
    done < <(find "$src_dir" -type f 2>/dev/null)
  done

  # 台账原子提交（temp+rename · 无论成败都落一份完整台账 → 防 torn read · AC-12）
  mv -f "$new_ledger" "$old_ledger" 2>/dev/null || { rm -f "$new_ledger" 2>/dev/null; MIRROR_SYNC_FAILED=1; }

  # 冲突/跳过报告 → session-start stderr（统一前缀）
  if [ -s "$conflict_report" ]; then
    echo "$MIRROR_SYNC_PREFIX 冲突/跳过报告（详见 $conflict_report）：" >&2
    while IFS= read -r _ln; do echo "$MIRROR_SYNC_PREFIX   $_ln" >&2; done < "$conflict_report"
  fi

  [ "$MIRROR_SYNC_FAILED" = "0" ]
}
