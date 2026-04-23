#!/usr/bin/env bash
# =============================================================================
# sync-all-secrets.sh
# Runs sync-secrets.sh across all service folders in apps/base/ starting
# from a given service name (alphabetically). The folder name is used as
# the prefix automatically.
#
# Usage (run from anywhere):
#   ~/c/DevOps-NCBA/k8s-core-gitops-1/sync-all-secrets.sh \
#     <starting-service-name> \
#     <vault-name> \
#     [--dry-run] [--skip-kv] [--skip-patch]
#
# Example:
#   ~/c/DevOps-NCBA/k8s-core-gitops-1/sync-all-secrets.sh \
#     ncba-ke-billers-jambopay \
#     ncba-core-test-kv
#
# Example (dry run first — always recommended):
#   ~/c/DevOps-NCBA/k8s-core-gitops-1/sync-all-secrets.sh \
#     ncba-ke-billers-jambopay \
#     ncba-core-test-kv \
#     --dry-run
# =============================================================================
set -euo pipefail

# ─── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

log_phase()  { echo -e "\n${BOLD}${CYAN}══ $1 ══${RESET}"; }
log_ok()     { echo -e "  ${GREEN}✔${RESET}  $1"; }
log_skip()   { echo -e "  ${DIM}–${RESET}  $1 ${DIM}(skipped)${RESET}"; }
log_warn()   { echo -e "  ${YELLOW}⚠${RESET}  $1"; }
log_err()    { echo -e "  ${RED}✘${RESET}  $1" >&2; }
log_info()   { echo -e "  ${DIM}→${RESET}  $1"; }

# ─── Resolve paths ────────────────────────────────────────────────────────────
# Always relative to this script's location regardless of where you run it from
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYNC_SCRIPT="${SCRIPT_DIR}/sync-secrets.sh"
BASE_DIR="${SCRIPT_DIR}/apps/base"

# ─── Args ─────────────────────────────────────────────────────────────────────
START_FROM="${1:-}"
VAULT_NAME="${2:-}"
EXTRA_FLAGS=()

shift 2 2>/dev/null || true
for arg in "$@"; do
  case "$arg" in
    --dry-run|--skip-kv|--skip-patch) EXTRA_FLAGS+=("$arg") ;;
    *) echo -e "${RED}Unknown flag: $arg${RESET}"; exit 1 ;;
  esac
done

# ─── Validate ─────────────────────────────────────────────────────────────────
if [[ -z "$START_FROM" || -z "$VAULT_NAME" ]]; then
  echo -e "${RED}Usage: $0 <starting-service-name> <vault-name> [--dry-run] [--skip-kv] [--skip-patch]${RESET}"
  echo -e "${DIM}Example:${RESET}"
  echo -e "  $0 ncba-ke-billers-jambopay ncba-core-test-kv"
  echo -e "  $0 ncba-ke-billers-jambopay ncba-core-test-kv --dry-run"
  exit 1
fi

[[ ! -f "$SYNC_SCRIPT" ]] && {
  log_err "sync-secrets.sh not found at: $SYNC_SCRIPT"
  log_err "Both scripts must be in the same folder (k8s-core-gitops-1/)"
  exit 1
}

[[ ! -d "$BASE_DIR" ]] && {
  log_err "Base dir not found: $BASE_DIR"
  exit 1
}

# ─── Print run config ─────────────────────────────────────────────────────────
echo -e "\n${BOLD}sync-all-secrets.sh${RESET}"
echo -e "  Base dir    : ${CYAN}$BASE_DIR${RESET}"
echo -e "  Start from  : ${CYAN}$START_FROM${RESET}"
echo -e "  Vault       : ${CYAN}$VAULT_NAME${RESET}"
echo -e "  Extra flags : ${DIM}${EXTRA_FLAGS[*]:-none}${RESET}"

# ─── Discover and filter services ─────────────────────────────────────────────
log_phase "Discovering services"

# Collect all service folders that have both required manifests
all_services=()
while IFS= read -r -d '' dir; do
  folder=$(basename "$dir")
  if [[ -f "${dir}/deployment.yaml" && -f "${dir}/secretproviderclass.yaml" ]]; then
    all_services+=("$folder")
  else
    log_warn "Skipping $folder — missing deployment.yaml or secretproviderclass.yaml"
  fi
done < <(find "$BASE_DIR" -mindepth 1 -maxdepth 1 -type d -print0 | sort -z)

if [[ ${#all_services[@]} -eq 0 ]]; then
  log_err "No valid service folders found in $BASE_DIR"
  exit 1
fi

# Check starting service exists
if ! printf '%s\n' "${all_services[@]}" | grep -Fxq "$START_FROM"; then
  log_err "Starting service not found: $START_FROM"
  echo -e "\n  ${DIM}Available services:${RESET}"
  printf '%s\n' "${all_services[@]}" | sed 's/^/    /'
  exit 1
fi

# Filter to only services from START_FROM onwards
services_to_run=()
found_start=false
for svc in "${all_services[@]}"; do
  if [[ "$svc" == "$START_FROM" ]]; then
    found_start=true
  fi
  if [[ "$found_start" == true ]]; then
    services_to_run+=("$svc")
  else
    log_skip "$svc"
  fi
done

echo -e "\n  ${BOLD}${#services_to_run[@]} service(s) to process:${RESET}"
printf '    %s\n' "${services_to_run[@]}"

# ─── Counters ─────────────────────────────────────────────────────────────────
total=${#services_to_run[@]}
succeeded=0
failed=0
failed_services=()

# ─── Process each service ─────────────────────────────────────────────────────
current=0
for svc in "${services_to_run[@]}"; do
  ((current++)) || true
  svc_dir="${BASE_DIR}/${svc}"

  log_phase "[$current/$total] $svc"

  # cd into the service folder and run sync-secrets.sh
  # PREFIX = folder name, which is already the correct naming convention
  if (cd "$svc_dir" && "$SYNC_SCRIPT" "$svc" "$VAULT_NAME" "${EXTRA_FLAGS[@]+"${EXTRA_FLAGS[@]}"}"); then
    log_ok "$svc — done"
    ((succeeded++)) || true
  else
    log_err "$svc — FAILED (continuing to next service)"
    ((failed++)) || true
    failed_services+=("$svc")
  fi
done

# ─── Final summary ────────────────────────────────────────────────────────────
log_phase "Batch Summary"

echo -e "
  Total services : $total
  ${GREEN}Succeeded${RESET}      : $succeeded
  ${RED}Failed${RESET}         : $failed
"

if [[ ${#failed_services[@]} -gt 0 ]]; then
  echo -e "  ${RED}${BOLD}Failed services:${RESET}"
  printf '    %s\n' "${failed_services[@]}"
  echo
fi

if [[ " ${EXTRA_FLAGS[*]:-} " == *"--dry-run"* ]]; then
  echo -e "  ${YELLOW}Dry-run — no files were modified, no KV uploads made.${RESET}\n"
fi

if [[ "$failed" -gt 0 ]]; then
  log_err "Some services failed. Review logs above."
  exit 1
fi

echo -e "  ${GREEN}${BOLD}All done.${RESET}\n"
