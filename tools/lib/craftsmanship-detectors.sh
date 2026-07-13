# craftsmanship-detectors.sh — detector implementations for craftsmanship-checker.sh
#
# Sourced by tools/craftsmanship-checker.sh. NOT executable on its own.
# Each detector reads a whole file (path in $1) and emits findings on STDOUT via
# the emit() function defined by the caller. Detectors never block directly;
# emit() owns severity/exit accounting. All detectors are language-aware where the
# audit requires it and fail-open (emit nothing) on unrecognized grammar.
#
# Rule provenance: rules/coding-standards.md §4 (size limits), §2.2 (layers),
# §9 (grab-bag), §1.3 (LSP), §5.2 (core instantiation).
#
# This file obeys coding-standards.md: functions <=50 lines, nesting <=3.

# Real path of THIS library, captured at source time. The LSP detector (§1.3)
# uses it to skip its own marker-pattern definitions: a checker that names the
# not-implemented markers as scan PATTERNS is not itself overriding LSP, and
# those tokens live inside a multi-line single-quoted awk program that per-line
# string-stripping cannot see. source: CRAFT-LSP-SELF-FP.
CRAFT_DETECTORS_REALPATH="$({ cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && printf '%s/%s' "$(pwd -P)" "$(basename "${BASH_SOURCE[0]}")"; } || echo "")"

# ── Language classification ────────────────────────────────────────────
# source: file extensions for the recognized-grammar set named in the audit
# (bash/python/js/ts/go/rust/swift). Unknown => "" => structural langs fail-open.
craft_lang_of() {
  case "$1" in
    *.sh|*.bash)            echo "bash" ;;
    *.py)                   echo "python" ;;
    *.js|*.jsx|*.mjs|*.cjs) echo "js" ;;
    *.ts|*.tsx)             echo "ts" ;;
    *.go)                   echo "go" ;;
    *.rs)                   echo "rust" ;;
    *.swift)                echo "swift" ;;
    *)                      echo "" ;;
  esac
}

# Brace-language set (depth + function/class scoring use braces for these).
craft_is_brace_lang() {
  case "$1" in
    js|ts|go|rust|swift) return 0 ;;
    *)                   return 1 ;;
  esac
}

# ── Detector 1: FILE_TOO_LONG (§4.1) — language-agnostic ────────────────
craft_d1_file_too_long() {
  local f="$1" max="$2" flex="$3" lines
  lines=$(wc -l < "$f" 2>/dev/null | tr -d ' ') || return 0
  [[ -z "$lines" ]] && return 0
  craft_size_finding "FILE_TOO_LONG" "SEV_FILE_TOO_LONG" "$f" 1 \
    "$lines" "$max" "$flex" "file has $lines lines (max $max)"
}

# ── Detector 2: NESTING_TOO_DEEP (§4.5) — brace depth or python indent ──
craft_d2_nesting_too_deep() {
  local f="$1" max="$2" lang="$3"
  if craft_is_brace_lang "$lang"; then
    craft_nest_brace "$f" "$max"
  elif [[ "$lang" == "python" ]]; then
    craft_nest_python "$f" "$max"
  fi
  # bash + unknown grammar: fail-open (no reliable block/indent contract).
}

# Brace-depth nesting. §4.5 governs nested CONTROL FLOW, but a raw { } counter
# cannot tell a control block from a DATA/object literal, and a brace inside a
# string/comment/regex is not nesting at all. To avoid the worst false counts we
# strip quoted spans, line comments and block comments before counting (so a
# brace in "..."/'...'/`...` or after // or inside /* */ can't poison depth).
# Robust control-vs-data brace classification in shell is still not achievable,
# so this detector is reported at ADVISE by default (SEV_NESTING_BRACE) and never
# blocks valid object/array literals — see craftsmanship-checker.sh CRAFT-NEST.
# Single awk pass (no per-line subprocess spawns). source: §4.5 NEST_MAX.
craft_nest_brace() {
  local f="$1" max="$2"
  awk -v max="$max" '
    function strip(s,   out,n,i,ch,q,esc,bc) {
      out=""; n=length(s); q=""; bc=0
      for(i=1;i<=n;i++){ ch=substr(s,i,1)
        if(bc){ if(ch=="*" && substr(s,i+1,1)=="/"){ bc=0; i++ }; continue }
        if(q!=""){ if(esc){esc=0} else if(ch=="\\"){esc=1} else if(ch==q){q=""}; continue }
        if(ch=="/" && substr(s,i+1,1)=="/") break
        if(ch=="/" && substr(s,i+1,1)=="*"){ bc=1; i++; continue }
        if(ch=="\"" || ch=="'\''" || ch=="`"){ q=ch; continue }
        out=out ch }
      return out
    }
    { code=strip($0); o=gsub(/\{/,"{",code); c=gsub(/\}/,"}",code)
      depth+=o-c; if(depth<0) depth=0
      if(depth>max){ s=$0; gsub(/\t/," ",s); printf "%d\t%d\t%s\n", NR, depth, s } }
  ' "$f" 2>/dev/null | craft_replay_nest "$f" "$max" "block depth" "SEV_NESTING_BRACE"
}

# Python indent-depth nesting: depth = leading spaces / 4 (tabs counted as 4).
# Only control headers (if/for/while/with/try/def/class/...) count, to avoid
# flagging wrapped expressions. Single awk pass. source: §4.5 NEST_MAX.
craft_nest_python() {
  local f="$1" max="$2"
  awk -v max="$max" '
    { line=$0; gsub(/\t/,"    ",line); if(line ~ /^[[:space:]]*(#|$)/) next
      match(line,/^ */); units=int(RLENGTH/4)
      if(units>max && line ~ /^[[:space:]]*(if|elif|else|for|while|with|try|except|def|class|match|case)[[:space:](:]/)
        { printf "%d\t%d\t%s\n", NR, units, line } }
  ' "$f" 2>/dev/null | craft_replay_nest "$f" "$max" "indent depth" "SEV_NESTING_TOO_DEEP"
}

# Shared: turn "line<TAB>depth<TAB>snippet" rows into NESTING findings. The SEV
# var name ($4) differs by language: python indent-depth is sound (BLOCK), while
# brace-depth is heuristic (SEV_NESTING_BRACE, ADVISE by default) — see §4.5.
craft_replay_nest() {
  local f="$1" max="$2" kind="$3" sevvar="${4:-SEV_NESTING_TOO_DEEP}" ln depth snip
  while IFS=$'\t' read -r ln depth snip; do
    [[ -z "$ln" ]] && continue
    craft_emit "NESTING_TOO_DEEP" "$sevvar" "$f" "$ln" \
      "$snip" "$kind $depth (max $max)"
  done
}

# ── Detector 3: FUNCTION_TOO_LONG (§4.2) — recognized langs only ────────
craft_d3_function_too_long() {
  local f="$1" max="$2" flex="$3" lang="$4"
  case "$lang" in
    python)              craft_fn_python "$f" "$max" "$flex" ;;
    bash)                craft_fn_bash "$f" "$max" "$flex" ;;
    js|ts|go|rust|swift) craft_fn_brace "$f" "$max" "$flex" "$lang" ;;
    *)                   : ;;  # unknown grammar: fail-open (ADVISE-only by absence)
  esac
}

# Python: a def/async-def block runs until a line dedents to <= the def's indent.
craft_fn_python() {
  local f="$1" max="$2" flex="$3"
  awk -v max="$max" '
    function emit(name,start,len){ printf "%d\t%s\t%d\n", start, name, len }
    /^[[:space:]]*(async[[:space:]]+)?def[[:space:]]/ {
      if (open) { len = NR-1 - sline; if (len>max) emit(sname,sline,len) }
      match($0,/^ */); sind=RLENGTH; sline=NR
      match($0,/def[[:space:]]+[A-Za-z_][A-Za-z0-9_]*/); sname=substr($0,RSTART,RLENGTH)
      open=1; next
    }
    open && $0 !~ /^[[:space:]]*(#|$)/ { match($0,/^ */); if (RLENGTH<=sind){ len=NR-1-sline; if(len>max) emit(sname,sline,len); open=0 } }
    END { if (open){ len=NR-sline; if(len>max) emit(sname,sline,len) } }
  ' "$f" 2>/dev/null | craft_replay_fn "$f" "$max" "$flex"
}

# Bash: function name(){ ... } or `name() {` — span by brace balance from header.
craft_fn_bash() {
  local f="$1" max="$2" flex="$3"
  awk -v max="$max" '
    function emit(name,start,len){ printf "%d\t%s\t%d\n", start, name, len }
    !open && /^[[:space:]]*(function[[:space:]]+)?[A-Za-z_][A-Za-z0-9_:-]*[[:space:]]*\(\)[[:space:]]*\{?/ {
      match($0,/[A-Za-z_][A-Za-z0-9_:-]*[[:space:]]*\(\)/); sname=substr($0,RSTART,RLENGTH)
      sline=NR; depth=0; open=1
    }
    open { o=gsub(/\{/,"{"); c=gsub(/\}/,"}"); depth+=o-c; if(depth<=0 && NR>sline){ len=NR-sline; if(len>max) emit(sname,sline,len); open=0 } }
  ' "$f" 2>/dev/null | craft_replay_fn "$f" "$max" "$flex"
}

# Brace languages: function/method headers, span by brace balance.
# CRAFT-FN-CONTROLHEADER-FP: a bare `keyword (...) {` form also matches
# control-flow headers (if/else/for/while/switch/catch/do/try), which are NOT
# functions and produced a wrong rule + wrong fn@NN attribution. A header now
# qualifies only when it carries an explicit function token (function/func/fn/
# def) or an arrow `=>`, OR is a generic `name(...) {` whose leading word is NOT
# a control-flow keyword. source: §4.2 FUNC_MAX (Martin 2008, Clean Code Ch.3).
# CRAFT-FN-IIFE-RECURSION-FP: browser-served JS modules without a bundler are
# commonly wrapped in an IIFE `(function () { ... })();` to create a module
# namespace without leaking globals. The scanner is a single-pass, outermost-
# span matcher: it has no recursion into an already-open span, so when the
# IIFE header itself matched is_fn_header() (it carries the `function` token),
# the ENTIRE module became one measured "function" and every internal function
# was swallowed unmeasured, guaranteeing FUNCTION_TOO_LONG on any IIFE-wrapped
# module over the line limit, by construction, regardless of the internal
# functions' actual sizes (root cause, not a size problem). An IIFE wrapper is
# a module-namespacing SCOPE, not a logic unit in the §4.2 sense — the limit
# targets units of business logic, not lexical scoping envelopes.
# source: §4.2 FUNC_MAX (Martin 2008, Clean Code Ch.3 — the size limit is
# about cyclomatic/logical complexity of a unit of work, not scope nesting).
# Fix: when a matched header is an IIFE wrapper, do NOT open a span for it;
# skip the header line and keep scanning at top level so headers of the
# functions DEFINED INSIDE the module are matched and measured individually
# (existing behavior for a genuine IIFE nested inside an already-open,
# measured function is unchanged: it stays swallowed by that outer span,
# same as any other nested construct — CRAFT-FN-CONTROLHEADER-FP above).
craft_fn_brace() {
  local f="$1" max="$2" flex="$3" lang="$4"
  awk -v max="$max" '
    function emit(name,start,len){ printf "%d\t%s\t%d\n", start, name, len }
    function is_fn_header(line,   w) {
      if (line ~ /(^|[^A-Za-z0-9_])(function|func|fn|def)([^A-Za-z0-9_]|$)/) return 1
      if (line ~ /=>[[:space:]]*\{/) return 1
      if (line ~ /[A-Za-z_][A-Za-z0-9_]*[[:space:]]*\([^;]*\)[[:space:]]*\{/) {
        w=line; sub(/^[[:space:]]*/,"",w); sub(/[^A-Za-z0-9_].*$/,"",w)
        if (w ~ /^(if|else|for|while|switch|catch|do|try)$/) return 0
        return 1
      }
      return 0
    }
    # IIFE wrapper header: after leading whitespace and an optional leading
    # `;` (ASI defensive prefix), the line opens with one of the grouping/
    # unary-operator tokens JS uses to force an expression context — `(`,
    # `!`, `+`, `-`, `~` — immediately followed by either the `function`
    # keyword (optionally `async function`) or an arrow-function header
    # `(...) => {`. Covers: `(function () {`, `;(function() {`,
    # `(function foo() {`, `!function() {`, `(() => {`, `((win) => {`.
    # Does NOT match a named/assigned arrow `var f = () => {` (line starts
    # with the identifier, not with one of the operator tokens).
    function is_iife_header(line,   w) {
      w=line; sub(/^[[:space:]]*;?[[:space:]]*/,"",w)
      if (w ~ /^[(!+~-][[:space:]]*(async[[:space:]]+)?function([^A-Za-z0-9_]|$)/) return 1
      if (w ~ /^[(!+~-].*\)[[:space:]]*=>[[:space:]]*\{/) return 1
      return 0
    }
    !open && is_fn_header($0) {
      if (is_iife_header($0)) next
      sline=NR; depth=0; open=1; sname="fn@"NR
    }
    open { o=gsub(/\{/,"{"); c=gsub(/\}/,"}"); depth+=o-c; if(depth<=0 && NR>sline){ len=NR-sline; if(len>max) emit(sname,sline,len); open=0 } }
  ' "$f" 2>/dev/null | craft_replay_fn "$f" "$max" "$flex"
}

# Shared: turn "start<TAB>name<TAB>len" rows into size findings at the head line.
craft_replay_fn() {
  local f="$1" max="$2" flex="$3" start name len head
  while IFS=$'\t' read -r start name len; do
    [[ -z "$start" ]] && continue
    head=$(sed -n "${start}p" "$f" 2>/dev/null)
    craft_size_finding "FUNCTION_TOO_LONG" "SEV_FUNCTION_TOO_LONG" "$f" "$start" \
      "$len" "$max" "$flex" "function ${name} spans $len lines (max $max)" "$head"
  done
}

# ── Detector 4: CLASS_TOO_LONG (§4.3) — recognized langs only ───────────
craft_d4_class_too_long() {
  local f="$1" max="$2" flex="$3" lang="$4"
  case "$lang" in
    python)              craft_class_python "$f" "$max" "$flex" ;;
    js|ts|go|rust|swift) craft_class_brace "$f" "$max" "$flex" ;;
    *)                   : ;;  # bash/unknown: no class construct => fail-open
  esac
}

craft_class_python() {
  local f="$1" max="$2" flex="$3"
  awk -v max="$max" '
    function emit(name,start,len){ printf "%d\t%s\t%d\n", start, name, len }
    /^[[:space:]]*class[[:space:]]/ {
      if (open){ len=NR-1-sline; if(len>max) emit(sname,sline,len) }
      match($0,/^ */); sind=RLENGTH; sline=NR
      match($0,/class[[:space:]]+[A-Za-z_][A-Za-z0-9_]*/); sname=substr($0,RSTART,RLENGTH)
      open=1; next
    }
    open && $0 !~ /^[[:space:]]*(#|$)/ { match($0,/^ */); if (RLENGTH<=sind){ len=NR-1-sline; if(len>max) emit(sname,sline,len); open=0 } }
    END { if (open){ len=NR-sline; if(len>max) emit(sname,sline,len) } }
  ' "$f" 2>/dev/null | craft_replay_class "$f" "$max" "$flex"
}

craft_class_brace() {
  local f="$1" max="$2" flex="$3"
  awk -v max="$max" '
    function emit(name,start,len){ printf "%d\t%s\t%d\n", start, name, len }
    !open && /(^|[[:space:]])(class|struct|interface|enum|impl)[[:space:]]+[A-Za-z_]/ {
      sline=NR; depth=0; open=1
      match($0,/(class|struct|interface|enum|impl)[[:space:]]+[A-Za-z_][A-Za-z0-9_]*/); sname=substr($0,RSTART,RLENGTH)
    }
    open { o=gsub(/\{/,"{"); c=gsub(/\}/,"}"); depth+=o-c; if(depth<=0 && NR>sline){ len=NR-sline; if(len>max) emit(sname,sline,len); open=0 } }
  ' "$f" 2>/dev/null | craft_replay_class "$f" "$max" "$flex"
}

craft_replay_class() {
  local f="$1" max="$2" flex="$3" start name len head
  while IFS=$'\t' read -r start name len; do
    [[ -z "$start" ]] && continue
    head=$(sed -n "${start}p" "$f" 2>/dev/null)
    craft_size_finding "CLASS_TOO_LONG" "SEV_CLASS_TOO_LONG" "$f" "$start" \
      "$len" "$max" "$flex" "class ${name} spans $len lines (max $max)" "$head"
  done
}

# ── Detector 5: PARAM_COUNT (§4.4) — recognized langs only ──────────────
# CRAFT-PARAM-CALLSITE-FP: §4.4 limits parameters in a function DECLARATION.
# The old matcher counted any `name(` — so it false-fired on CALL sites
# (compute(a,b,c,d,e)), collection-constructor calls (dict(a=1,...),
# frozenset({...})) and prose inside docstrings/comments. We now require a
# declaration HEADER: an explicit def/function/func/fn/method/sub keyword, or a
# named arrow (name = (...) => / name: (...) =>). Comment lines and Python
# triple-quoted docstring spans are skipped so prose never counts as params.
# source: §4.4 PARAM_MAX (Martin 2008, Clean Code Ch.3).
craft_d5_param_count() {
  local f="$1" max="$2" lang="$3"
  case "$lang" in
    python|js|ts|go|rust|swift) : ;;
    *) return 0 ;;  # bash (positional $1..) + unknown grammar: fail-open
  esac
  awk -v max="$max" '
    function is_decl(line) {
      if (line ~ /(^|[^A-Za-z0-9_])(def|function|func|fn|method|sub)[[:space:]]+[A-Za-z_][A-Za-z0-9_]*[[:space:]]*\(/) return 1
      if (line ~ /[A-Za-z_][A-Za-z0-9_$]*[[:space:]]*[:=][[:space:]]*\([^)]*\)[[:space:]]*=>/) return 1
      return 0
    }
    { line=$0
      if (in_doc) { if (line ~ /("""|'\'''\'''\'')/) in_doc=0; next }
      if (line ~ /^[[:space:]]*("""|'\'''\'''\'')/ && line !~ /("""|'\'''\'''\'').*("""|'\'''\'''\'')/) { in_doc=1; next }
      if (line ~ /^[[:space:]]*(#|\/\/|\*|-)/) next
      if (!is_decl(line)) next
      i=index(line,"("); if(i==0) next
      n=split(substr(line,i),ch,""); inner=""; d=0
      for(k=1;k<=n;k++){ c=ch[k]
        if(c=="("){d++; if(d==1) continue} else if(c==")"){d--; if(d==0) break}
        if(d>=1) inner=inner c }
      gsub(/^[[:space:]]+|[[:space:]]+$/,"",inner)
      if(inner=="") next
      cnt=split(inner,parts,","); real=0
      for(k=1;k<=cnt;k++){ p=parts[k]; gsub(/^[[:space:]]+|[[:space:]]+$/,"",p); if(p!="" && p!="self" && p!="cls") real++ }
      if(real>max) printf "%d\t%d\t%s\n", NR, real, line
    }
  ' "$f" 2>/dev/null | craft_replay_param "$f" "$max"
}

craft_replay_param() {
  local f="$1" max="$2" ln cnt head
  while IFS=$'\t' read -r ln cnt head; do
    [[ -z "$ln" ]] && continue
    craft_emit "PARAM_COUNT" "SEV_PARAM_COUNT" "$f" "$ln" "$head" \
      "$cnt parameters (max $max)"
  done
}

# ── Detector 6: LAYER_VIOLATION (§2.2) — conventional layer dirs only ───
# Inner layers must not import outer ones. Rank: shared<core<application<
# infrastructure<handlers<server. Emit nothing when no path segment is a known
# layer (fail-open on polyglot repos). source: §2.2 dependency rule.
craft_d6_layer_violation() {
  local f="$1" mylayer
  mylayer=$(craft_layer_of "$f")
  [[ -z "$mylayer" ]] && return 0   # fail-open: file not in a known layer
  local myrank; myrank=$(craft_layer_rank "$mylayer")
  { grep -nE "(import|from|require|use|#include)[^A-Za-z]" "$f" 2>/dev/null || true; } | \
    craft_layer_scan "$f" "$mylayer" "$myrank"
}

craft_layer_scan() {
  local f="$1" mylayer="$2" myrank="$3" ln text seg orank
  while IFS=: read -r ln text; do
    for seg in core domain application infrastructure handlers server shared adapters; do
      if [[ "$text" =~ (^|[^A-Za-z])$seg([^A-Za-z]|$) ]]; then
        orank=$(craft_layer_rank "$(craft_norm_layer "$seg")")
        if [[ -n "$orank" ]] && [[ "$orank" -gt "$myrank" ]]; then
          craft_emit "LAYER_VIOLATION" "SEV_LAYER_VIOLATION" "$f" "$ln" \
            "$text" "$mylayer imports outer layer $seg"
        fi
      fi
    done
  done
}

# Map a path to its layer by directory segment; "" if none recognized.
craft_layer_of() {
  local seg
  for seg in handlers server infrastructure adapters application domain core shared; do
    [[ "$1" =~ (^|/)$seg(/|$) ]] && { craft_norm_layer "$seg"; return 0; }
  done
  echo ""
}

# Normalize synonyms: domain->core, adapters->infrastructure.
craft_norm_layer() {
  case "$1" in
    domain)   echo "core" ;;
    adapters) echo "infrastructure" ;;
    *)        echo "$1" ;;
  esac
}

# Layer rank (higher = more outward). "" for unknown.
craft_layer_rank() {
  case "$1" in
    shared)         echo 0 ;;
    core)           echo 1 ;;
    application)    echo 2 ;;
    infrastructure) echo 3 ;;
    handlers)       echo 4 ;;
    server)         echo 5 ;;
    *)              echo "" ;;
  esac
}

# ── Detector 7: GRABBAG_NAME (§9) — basename grab-bag, ADVISE ────────────
# common/shared are sanctioned §2.1 layer names — excluded. source: §9.
craft_d7_grabbag_name() {
  local f="$1" base; base=$(basename "$f")
  local stem="${base%.*}"
  case "$stem" in
    utils|util|helpers|helper|misc)
      craft_emit "GRABBAG_NAME" "SEV_GRABBAG_NAME" "$f" 1 "$base" \
        "grab-bag module name '$stem' (§9)" ;;
  esac
}

# ── Detector 8: LSP_NOTIMPL (§1.3) — literal not-implemented, ADVISE ────
# CRAFT-LSP-SELF-FP: a marker that appears only inside a STRING literal or a
# COMMENT is not an LSP override — e.g. this checker's own grep pattern string
# named the markers and (under strict) blocked the detector lib itself. We strip
# quoted spans and line/block comments per line before testing the markers, so
# only markers in executable code are reported. source: §1.3 (Liskov 1987).
craft_d8_lsp_notimpl() {
  local f="$1" fr
  fr="$({ cd "$(dirname "$f")" 2>/dev/null && printf '%s/%s' "$(pwd -P)" "$(basename "$f")"; } || echo "")"
  [[ -n "$CRAFT_DETECTORS_REALPATH" && "$fr" == "$CRAFT_DETECTORS_REALPATH" ]] && return 0
  awk '
    function strip(s,   out,n,i,ch,q,esc,bc) {
      out=""; n=length(s); q=""; bc=0
      for(i=1;i<=n;i++){ ch=substr(s,i,1)
        if(bc){ if(ch=="*" && substr(s,i+1,1)=="/"){ bc=0; i++ }; continue }
        if(q!=""){ if(esc){esc=0} else if(ch=="\\"){esc=1} else if(ch==q){q=""}; continue }
        if(ch=="#") break
        if(ch=="/" && substr(s,i+1,1)=="/") break
        if(ch=="/" && substr(s,i+1,1)=="*"){ bc=1; i++; continue }
        if(ch=="\"" || ch=="'\''" || ch=="`"){ q=ch; continue }
        out=out ch }
      return out
    }
    { code=strip($0)
      # Identifier/macro markers must live in CODE (post-strip), so a marker
      # named inside a string/comment cannot fire.
      hit = (code ~ /(NotImplementedError|UnsupportedOperation|todo!\(\)|unimplemented!\(\))/)
      # panic("not implemented") embeds its own string literal; strip blanks the
      # message, so require the panic CALL to survive stripping (code, not a
      # comment) before testing the raw line for the message text.
      if (!hit && code ~ /panic[[:space:]]*\(/ && $0 ~ /panic\("not implemented"\)/) hit = 1
      if (hit) printf "%d:%s\n", NR, $0 }
  ' "$f" 2>/dev/null | craft_replay_grep "LSP_NOTIMPL" "SEV_LSP_NOTIMPL" "$f" \
    "literal not-implemented marker (§1.3 LSP risk)"
}

# ── Detector 9: CORE_CONCRETE_INSTANTIATION (§5.2) — ADVISE, default OFF ─
# Concrete infra type built on a core/domain/application path. source: §5.2.
craft_d9_core_instantiation() {
  local f="$1" layer; layer=$(craft_layer_of "$f")
  case "$layer" in
    core|application) ;;
    *) return 0 ;;  # only inner layers; else fail-open
  esac
  { grep -nE '(new |= )[A-Za-z_][A-Za-z0-9_]*(Gateway|Repository|Repo|Client|Adapter|Service)[[:space:]]*\(' \
    "$f" 2>/dev/null || true; } | craft_replay_grep "CORE_CONCRETE_INSTANTIATION" \
    "SEV_CORE_INSTANTIATION" "$f" "concrete infra type instantiated in $layer (§5.2)"
}

# Shared: turn `grep -n` rows (line:text) into findings.
craft_replay_grep() {
  local rule="$1" sevvar="$2" f="$3" msg="$4" ln text
  while IFS=: read -r ln text; do
    [[ -z "$ln" ]] && continue
    craft_emit "$rule" "$sevvar" "$f" "$ln" "$text" "$msg"
  done
}
