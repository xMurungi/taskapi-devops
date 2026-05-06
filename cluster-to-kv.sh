# chmod +x cluster-to-kv.sh
# ./cluster-to-kv.sh --vault ncba-core-test-kv --dry-run

#!/usr/bin/env bash
# =============================================================================
# cluster-to-kv.sh
# Reconciles Kubernetes secrets (cluster as source of truth) with Azure KV.
# Uses kubectl directly — no jq, no yq, no SPC files, no manifests.
#
# Requirements: kubectl, az (Azure CLI), base64
#
# Usage:
#   ./cluster-to-kv.sh --vault ncba-core-test-kv [--dry-run]
#
# kubectl setup notes:
#   - Check current context : kubectl config current-context
#   - List contexts         : kubectl config get-contexts
#   - Switch context        : kubectl config use-context <context-name>
#
# Add to .gitignore:
#   cluster-kv-audit-*.log
# =============================================================================
set -euo pipefail

# ─── Platform-aware az command ────────────────────────────────────────────────
if command -v az.cmd &>/dev/null; then
  AZ="az.cmd"
elif command -v az &>/dev/null; then
  AZ="az"
else
  echo "Azure CLI (az) not found." >&2; exit 1
fi

# ─── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GRN='\033[0;32m'; CYN='\033[0;36m'
YEL='\033[1;33m'; BOLD='\033[1m'; DIM='\033[2m'; RST='\033[0m'

phase() { echo -e "\n${BOLD}${CYN}══ $1 ══${RST}"; }
ok()    { echo -e "  ${GRN}✔${RST}  $1"; }
err()   { echo -e "  ${RED}✘${RST}  $1" >&2; }
info()  { echo -e "  ${DIM}→${RST}  $1"; }
warn()  { echo -e "  ${YEL}⚠${RST}  $1"; }

# ─── Log ──────────────────────────────────────────────────────────────────────
TIMESTAMP=$(date +"%Y%m%d-%H%M%S")
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/cluster-kv-audit-${TIMESTAMP}.log"

log() { echo "$1" >> "$LOG_FILE"; }
log_section() { log ""; log "────────────────────────────────────"; log "  $1"; log "────────────────────────────────────"; }

# ─── Args ─────────────────────────────────────────────────────────────────────
VAULT=""; DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --vault)   VAULT="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    *) echo "Usage: $0 --vault <vault-name> [--dry-run]"; exit 1 ;;
  esac
done

[[ -z "$VAULT" ]] && { echo "Usage: $0 --vault <vault-name> [--dry-run]"; exit 1; }

# ─── Dependency check ─────────────────────────────────────────────────────────
for cmd in kubectl base64; do
  command -v "$cmd" &>/dev/null || { err "Required: $cmd not found"; exit 1; }
done

log "cluster-to-kv.sh — $(date)"
log "========================================"
log "Vault: $VAULT | Dry run: $DRY_RUN"
echo -e "\n  ${DIM}Log: $LOG_FILE${RST}"
[[ "$DRY_RUN" == true ]] && echo -e "\n  ${YEL}${BOLD}DRY RUN — no changes will be made${RST}"

# ─── System secret filter ─────────────────────────────────────────────────────
is_system_secret() {
  local name="$1" type="$2"
  case "$type" in
    kubernetes.io/service-account-token|\
    kubernetes.io/dockerconfigjson|kubernetes.io/dockercfg|\
    helm.sh/release.v1|bootstrap.kubernetes.io/token) return 0 ;;
  esac
  case "$name" in
    secrets-store-creds|flux-acr-password|default-token*) return 0 ;;
  esac
  [[ "$name" == sh.helm.release* ]] && return 0
  echo "$name" | grep -qE '\-token\-[a-z0-9]+$' && return 0
  return 1
}

# ─── Hash ─────────────────────────────────────────────────────────────────────
safe_hash() {
  if command -v sha256sum &>/dev/null; then
    printf '%s' "$1" | sha256sum | awk '{print $1}'
  else
    printf '%s' "$1" | shasum -a 256 | awk '{print $1}'
  fi
}

# ─── Visual comparison ────────────────────────────────────────────────────────
show_comparison() {
  local name="$1" cv="$2" kv="$3"
  local ch kh
  ch=$(safe_hash "$cv"); kh=$(safe_hash "$kv")
  echo -e "\n  ${BOLD}────────────────────────────────────${RST}"
  echo -e "  ${BOLD}Secret       :${RST} $name"
  echo -e "  ${BOLD}Cluster value:${RST} $cv"
  echo -e "  ${BOLD}KV value     :${RST} ${kv:-[NOT IN KV]}"
  echo -e "  ${BOLD}Cluster hash :${RST} ${ch:0:32}…"
  echo -e "  ${BOLD}KV hash      :${RST} ${kh:0:32}…"
  if [[ "$ch" == "$kh" ]]; then
    echo -e "  ${GRN}✔ Match${RST}"
    echo -e "  ${BOLD}────────────────────────────────────${RST}"
    return 0
  else
    echo -e "  ${RED}✘ Mismatch${RST}"
    echo -e "  ${BOLD}────────────────────────────────────${RST}"
    return 1
  fi
}

# ─── KV helpers ───────────────────────────────────────────────────────────────
kv_exists() { $AZ keyvault secret show --vault-name "$VAULT" --name "$1" --query "value" -o tsv &>/dev/null; }
kv_get()    { $AZ keyvault secret show --vault-name "$VAULT" --name "$1" --query "value" -o tsv 2>/dev/null | tr -d '\r'; }
kv_version(){ $AZ keyvault secret show --vault-name "$VAULT" --name "$1" --query "id" -o tsv 2>/dev/null | rev | cut -d'/' -f1 | rev | tr -d '\r'; }

kv_set() {
  local name="$1" value="$2" tmp rc=0 out
  tmp=$(mktemp)
  printf '%s' "$value" > "$tmp"
  out=$($AZ keyvault secret set --vault-name "$VAULT" --name "$name" --file "$tmp" --output none 2>&1) || rc=$?
  rm -f "$tmp"; echo "$out"; return $rc
}

# ─── Step 1: Context ──────────────────────────────────────────────────────────
phase "Step 1 — kubectl context"

CONTEXT=$(kubectl config current-context 2>/dev/null) || { err "kubectl not configured"; exit 1; }
echo -e "\n  ${BOLD}Current context:${RST} ${CYN}${CONTEXT}${RST}"
log "Context: $CONTEXT"

read -rp "$(echo -e "\n  ${YEL}?${RST}  Is this the correct cluster? [y/n]: ")" confirm
[[ "$confirm" != "y" ]] && { echo "  Run: kubectl config use-context <name>"; exit 0; }

# ─── Step 2: Namespace ────────────────────────────────────────────────────────
phase "Step 2 — Select namespace(s)"

mapfile -t ALL_NS < <(
  kubectl get namespaces -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
)

echo -e "\n  ${BOLD}Available namespaces:${RST}"
for i in "${!ALL_NS[@]}"; do printf "    %3d. %s\n" "$((i+1))" "${ALL_NS[$i]}"; done
echo "      0. All namespaces"

TARGET_NS=()
while true; do
  read -rp "$(echo -e "\n  ${YEL}?${RST}  Enter number or name: ")" ns_choice
  if [[ "$ns_choice" == "0" ]]; then
    TARGET_NS=("${ALL_NS[@]}"); info "Scanning: ALL"; break
  fi
  if [[ "$ns_choice" =~ ^[0-9]+$ ]]; then
    idx=$((ns_choice - 1))
    if [[ $idx -ge 0 && $idx -lt ${#ALL_NS[@]} ]]; then
      TARGET_NS=("${ALL_NS[$idx]}"); info "Scanning: ${TARGET_NS[0]}"; break
    fi
  fi
  matched=false
  for ns in "${ALL_NS[@]}"; do
    if [[ "$ns" == "$ns_choice" ]]; then
      TARGET_NS=("$ns"); info "Scanning: $ns"; matched=true; break
    fi
  done
  [[ "$matched" == true ]] && break
  echo "  Invalid. Try again."
done

log "Namespaces: ${TARGET_NS[*]}"

# ─── Step 3: Collect secrets ──────────────────────────────────────────────────
phase "Step 3 — Collecting secrets from cluster"

ENTRY_KV_NAME=()
ENTRY_CLUSTER_VAL=()
ENTRY_NS=()

for ns in "${TARGET_NS[@]}"; do
  info "Scanning namespace: $ns"

  # Get all secret names and types — one kubectl call per namespace
  mapfile -t SECRET_LINES < <(
    kubectl get secrets -n "$ns" \
      -o jsonpath='{range .items[*]}{.metadata.name}{"|"}{.type}{"\n"}{end}' \
      2>/dev/null || true
  )

  total_in_ns=${#SECRET_LINES[@]}
  app_count=0

  for line in "${SECRET_LINES[@]}"; do
    [[ -z "$line" ]] && continue
    secret_name="${line%%|*}"
    secret_type="${line##*|}"

    is_system_secret "$secret_name" "$secret_type" && continue
    ((app_count++)) || true

    # Get all keys for this secret — go-template is most reliable for arbitrary key names
    mapfile -t KEY_LINES < <(
      kubectl get secret "$secret_name" -n "$ns" \
        -o go-template='{{range $k, $v := .data}}{{$k}}{{"\n"}}{{end}}' \
        2>/dev/null | grep -v '^$' || true
    )

    [[ ${#KEY_LINES[@]} -eq 0 ]] && continue

    for key in "${KEY_LINES[@]}"; do
      [[ -z "$key" ]] && continue

      # Get b64 value for this key using jsonpath index notation
      b64val=$(kubectl get secret "$secret_name" -n "$ns" \
        -o jsonpath="{.data['${key}']}" 2>/dev/null | tr -d '\r\n' || echo "")

      if [[ -z "$b64val" ]]; then
        cluster_val=""
      else
        cluster_val=$(printf '%s' "$b64val" | base64 --decode 2>/dev/null | tr -d '\r' || echo "")
      fi

      ENTRY_KV_NAME+=("$key")
      ENTRY_CLUSTER_VAL+=("$cluster_val")
      ENTRY_NS+=("$ns")
    done
  done

  skipped=$((total_in_ns - app_count))
  info "  Found $app_count app secret(s), skipped $skipped system secret(s)"
done

total=${#ENTRY_KV_NAME[@]}
info "Total keys to check: $total"
log "Total entries: $total"

if [[ "$total" -eq 0 ]]; then
  warn "No secrets found."; exit 0
fi

# ─── Step 4: Check against KV ────────────────────────────────────────────────
phase "Step 4 — Checking against Key Vault"

MISSING_NAMES=(); MISSING_VALUES=(); MISSING_NS=()
MISMATCH_NAMES=(); MISMATCH_CLUSTER=(); MISMATCH_KV=(); MISMATCH_NS=()
MATCHED=0; DECODE_ERRORS=0

for i in "${!ENTRY_KV_NAME[@]}"; do
  kv_name="${ENTRY_KV_NAME[$i]}"
  cluster_val="${ENTRY_CLUSTER_VAL[$i]}"
  ns="${ENTRY_NS[$i]}"
  current=$((i + 1))

  echo -e "\n  ${BOLD}[$current/$total]${RST} $kv_name  ${DIM}(ns: $ns)${RST}"
  log_section "[$current/$total] $kv_name | ns: $ns"

  if [[ -z "$cluster_val" ]]; then
    warn "Could not decode — skipping"
    log "  STATUS: DECODE ERROR"
    ((DECODE_ERRORS++)) || true
    continue
  fi

  log "  CLUSTER VALUE : $cluster_val"
  log "  CLUSTER HASH  : $(safe_hash "$cluster_val")"

  if ! kv_exists "$kv_name"; then
    warn "NOT in KV"
    log "  STATUS: MISSING FROM KV"
    MISSING_NAMES+=("$kv_name")
    MISSING_VALUES+=("$cluster_val")
    MISSING_NS+=("$ns")
    continue
  fi

  kv_val=$(kv_get "$kv_name")
  log "  KV VALUE : $kv_val"
  log "  KV HASH  : $(safe_hash "$kv_val")"

  if show_comparison "$kv_name" "$cluster_val" "$kv_val"; then
    log "  STATUS: MATCH"
    ((MATCHED++)) || true
  else
    log "  STATUS: MISMATCH"
    MISMATCH_NAMES+=("$kv_name")
    MISMATCH_CLUSTER+=("$cluster_val")
    MISMATCH_KV+=("$kv_val")
    MISMATCH_NS+=("$ns")
  fi
done

# ─── Step 5: Summary ──────────────────────────────────────────────────────────
phase "Step 5 — Summary"

echo -e "
  ${GRN}Matched${RST}          : $MATCHED
  ${YEL}Missing from KV${RST} : ${#MISSING_NAMES[@]}
  ${YEL}Mismatch${RST}         : ${#MISMATCH_NAMES[@]}
  ${DIM}Decode errors${RST}    : $DECODE_ERRORS
"

log_section "SUMMARY"
log "  Matched: $MATCHED | Missing: ${#MISSING_NAMES[@]} | Mismatch: ${#MISMATCH_NAMES[@]} | Errors: $DECODE_ERRORS"

if [[ ${#MISSING_NAMES[@]} -gt 0 ]]; then
  echo -e "\n  ${BOLD}Missing from KV:${RST}"
  log_section "MISSING FROM KV"
  for i in "${!MISSING_NAMES[@]}"; do
    echo -e "    ${RED}✘${RST} ${MISSING_NAMES[$i]}  ${DIM}(ns: ${MISSING_NS[$i]})${RST}"
    log "  ${MISSING_NAMES[$i]} | ns: ${MISSING_NS[$i]} | value: ${MISSING_VALUES[$i]}"
  done
fi

if [[ ${#MISMATCH_NAMES[@]} -gt 0 ]]; then
  echo -e "\n  ${BOLD}Mismatched:${RST}"
  log_section "MISMATCHES"
  for i in "${!MISMATCH_NAMES[@]}"; do
    echo -e "    ${YEL}≠${RST} ${MISMATCH_NAMES[$i]}  ${DIM}(ns: ${MISMATCH_NS[$i]})${RST}"
    log "  ${MISMATCH_NAMES[$i]} | cluster: ${MISMATCH_CLUSTER[$i]} | kv: ${MISMATCH_KV[$i]}"
  done
fi

if [[ "$DRY_RUN" == true ]]; then
  echo -e "\n  ${YEL}Dry run — no changes made.${RST}\n"; exit 0
fi

# ─── Step 6: Upload missing ───────────────────────────────────────────────────
if [[ ${#MISSING_NAMES[@]} -gt 0 ]]; then
  phase "Step 6 — Upload missing secrets to KV"

  read -rp "$(echo -e "\n  ${YEL}?${RST}  Upload ${#MISSING_NAMES[@]} missing secret(s)? [y/n]: ")" bulk
  if [[ "$bulk" == "y" ]]; then
    for i in "${!MISSING_NAMES[@]}"; do
      kv_name="${MISSING_NAMES[$i]}"
      cluster_val="${MISSING_VALUES[$i]}"

      echo -e "\n  ${BOLD}$kv_name${RST}"
      info "Value : $cluster_val"
      info "Hash  : $(safe_hash "$cluster_val" | cut -c1-32)…"

      read -rp "$(echo -e "\n  ${YEL}?${RST}  Upload? [y/skip/pause]: ")" confirm
      case "$confirm" in
        skip)  warn "Skipped"; log "  SKIPPED: $kv_name"; continue ;;
        pause) read -rp "  Paused. Press Enter..."; log "  PAUSED: $kv_name"; continue ;;
        y) ;;
        *) warn "Invalid — skipping"; continue ;;
      esac

      upload_out=$(kv_set "$kv_name" "$cluster_val") && upload_ok=true || upload_ok=false

      if [[ "$upload_ok" == false ]]; then
        err "Upload failed: $upload_out"
        log "  UPLOAD FAILED: $kv_name | $upload_out"
        read -rp "$(echo -e "\n  ${YEL}?${RST}  [pause/skip]: ")" action
        [[ "$action" == "pause" ]] && read -rp "  Press Enter..."
        continue
      fi

      info "Verifying…"
      kv_val_after=$(kv_get "$kv_name")

      if show_comparison "$kv_name" "$cluster_val" "$kv_val_after"; then
        version=$(kv_version "$kv_name")
        ok "Uploaded and verified | version: $version"
        log "  UPLOADED OK: $kv_name | version: $version | value: $cluster_val"
      else
        err "Checksum mismatch after upload!"
        log "  UPLOAD MISMATCH: $kv_name"
        read -rp "$(echo -e "\n  ${YEL}?${RST}  [retry/skip/pause]: ")" action
        case "$action" in
          retry) kv_set "$kv_name" "$cluster_val" >/dev/null; ok "Retried"; log "  RETRIED: $kv_name" ;;
          pause) read -rp "  Press Enter..." ;;
        esac
      fi
    done
  fi
fi

# ─── Step 7: Handle mismatches ────────────────────────────────────────────────
if [[ ${#MISMATCH_NAMES[@]} -gt 0 ]]; then
  phase "Step 7 — Handle mismatched secrets"
  warn "Cluster is source of truth — overwrite will replace KV value."

  for i in "${!MISMATCH_NAMES[@]}"; do
    kv_name="${MISMATCH_NAMES[$i]}"
    cluster_val="${MISMATCH_CLUSTER[$i]}"
    kv_val="${MISMATCH_KV[$i]}"

    echo -e "\n  ${BOLD}$kv_name${RST}"
    show_comparison "$kv_name" "$cluster_val" "$kv_val" || true

    read -rp "$(echo -e "\n  ${YEL}?${RST}  [overwrite/skip/pause]: ")" action
    case "$action" in
      skip)      log "  SKIPPED: $kv_name"; continue ;;
      pause)     read -rp "  Press Enter..."; log "  PAUSED: $kv_name"; continue ;;
      overwrite) ;;
      *)         warn "Invalid — skipping"; continue ;;
    esac

    upload_out=$(kv_set "$kv_name" "$cluster_val") && upload_ok=true || upload_ok=false
    if [[ "$upload_ok" == false ]]; then
      err "Upload failed: $upload_out"; log "  OVERWRITE FAILED: $kv_name"; continue
    fi

    kv_val_after=$(kv_get "$kv_name")
    if show_comparison "$kv_name" "$cluster_val" "$kv_val_after"; then
      ok "Overwritten and verified"; log "  OVERWRITTEN OK: $kv_name | value: $cluster_val"
    else
      err "Still mismatched!"; log "  OVERWRITE MISMATCH: $kv_name"
    fi
  done
fi

# ─── Done ─────────────────────────────────────────────────────────────────────
phase "Done"
echo -e "  ${GRN}${BOLD}Complete.${RST}"
echo -e "  ${DIM}Log: $LOG_FILE${RST}\n"
log ""; log "========================================"; log "COMPLETE"
