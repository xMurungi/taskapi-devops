~/c/DevOps-NCBA/k8s-core-gitops-1/sync-secrets.sh ncbakemobilemoneyapi-mpesa-daraja-adapter ncba-core-test-kv --dry-run

~/c/DevOps-NCBA/k8s-core-gitops-1/sync-secrets.sh \
  ncbakemobilemoneyapi-mpesa-daraja-adapter \
  ncba-core-test-kv

cd /c/DevOps-NCBA/k8s-core-gitops-1/services/mpesa-daraja-adapter

~/c/DevOps-NCBA/k8s-core-gitops-1/sync-secrets.sh \
  ncbakemobilemoneyapi-mpesa-daraja-adapter \
  ncba-core-test-kv \
  --dry-run

#!/usr/bin/env bash
# =============================================================================
# sync-secrets.sh
# Reads sensitive env vars from a deployment YAML, uploads their plaintext
# values to Azure Key Vault, patches the SPC, and patches the deployment.
#
# Usage:
#   ./sync-secrets.sh <service-folder> <prefix> <vault-name> [--dry-run] [--skip-kv] [--skip-patch]
#
# Example:
#   ~/c/DevOps-NCBA/k8s-core-gitops-1/sync-secrets.sh \
#     /c/DevOps-NCBA/k8s-core-gitops-1/services/mpesa-daraja-adapter \
#     ncbakemobilemoneyapi-mpesa-daraja-adapter \
#     ncba-core-test-kv
#
# Expects these files inside <service-folder>:
#   deployment.yaml
#   secretproviderclass.yaml
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
log_dryrun() { echo -e "  ${YELLOW}[DRY-RUN]${RESET} $1"; }

# ─── Args ─────────────────────────────────────────────────────────────────────
# Usage: script.sh <prefix> <vault-name> [--dry-run] [--skip-kv] [--skip-patch]
# Run from inside the service folder — it uses your current directory automatically.
PREFIX="${1:-}"
VAULT_NAME="${2:-}"
SERVICE_DIR="${PWD}"
DRY_RUN=false
SKIP_KV=false
SKIP_PATCH=false

# Parse optional flags from remaining args
shift 2 2>/dev/null || true
for arg in "$@"; do
  case "$arg" in
    --dry-run)    DRY_RUN=true   ;;
    --skip-kv)    SKIP_KV=true   ;;
    --skip-patch) SKIP_PATCH=true ;;
    *) echo -e "${RED}Unknown flag: $arg${RESET}"; exit 1 ;;
  esac
done

# ─── Validate ─────────────────────────────────────────────────────────────────
if [[ -z "$PREFIX" || -z "$VAULT_NAME" ]]; then
  echo -e "${RED}Usage: $0 <prefix> <vault-name> [--dry-run] [--skip-kv] [--skip-patch]${RESET}"
  echo -e "${DIM}cd into the service folder first, then run:${RESET}"
  echo -e "  cd /c/DevOps-NCBA/k8s-core-gitops-1/services/mpesa-daraja-adapter"
  echo -e "  $0 ncbakemobilemoneyapi-mpesa-daraja-adapter ncba-core-test-kv"
  exit 1
fi

DEPLOYMENT_FILE="${SERVICE_DIR}/deployment.yaml"
SPC_FILE="${SERVICE_DIR}/secretproviderclass.yaml"

[[ ! -f "$DEPLOYMENT_FILE" ]] && { log_err "Not found: $DEPLOYMENT_FILE"; exit 1; }
[[ ! -f "$SPC_FILE" ]]        && { log_err "Not found: $SPC_FILE";        exit 1; }

# ─── Dependency check ─────────────────────────────────────────────────────────
for cmd in yq az sha256sum; do
  if ! command -v "$cmd" &>/dev/null; then
    log_err "Required tool not found: $cmd"
    exit 1
  fi
done

# ─── Git Bash sha256sum fix ───────────────────────────────────────────────────
# Git Bash on Windows injects \r into strings — strip before hashing
safe_hash() {
  printf '%s' "$1" | tr -d '\r' | sha256sum | awk '{print $1}'
}

# ─── Helpers ──────────────────────────────────────────────────────────────────
is_sensitive() {
  echo "$1" | grep -Eiq \
    'key|secret|password|connectionstring|token|credential|apikey|clientsecret|clientid|subscriptionkey'
}

to_kv_name() {
  printf '%s' "$1" \
    | tr -d '\r' \
    | tr '[:upper:]' '[:lower:]' \
    | sed 's/__/-/g; s/_/-/g; s/\./-/g; s/-\+/-/g; s/^-//; s/-$//'
}

# ─── Counters ─────────────────────────────────────────────────────────────────
kv_uploaded=0
kv_skipped=0
kv_empty=0
kv_failed=0
patch_deployment=0
patch_spc_objects=0
patch_spc_secretobjects=0

tmp_objects=$(mktemp)
trap 'rm -f "$tmp_objects"' EXIT

# ─── Print run config ─────────────────────────────────────────────────────────
echo -e "\n${BOLD}sync-secrets.sh${RESET}"
echo -e "  Service dir : ${CYAN}$SERVICE_DIR${RESET}"
echo -e "  Prefix      : ${CYAN}$PREFIX${RESET}"
echo -e "  Vault       : ${CYAN}$VAULT_NAME${RESET}"
echo -e "  Dry run     : $DRY_RUN"
echo -e "  Skip KV     : $SKIP_KV"
echo -e "  Skip patch  : $SKIP_PATCH"

# ─── Phase 0: Read existing SPC state ─────────────────────────────────────────
log_phase "Phase 0 — Reading existing SPC state"

existing_objects=$(yq -r '
  .spec.parameters.objects // ""
  | split("\n")[]
  | select(test("objectName:"))
  | sub(".*objectName: "; "") | ltrimstr(" ") | rtrimstr(" ")
' "$SPC_FILE" 2>/dev/null | tr -d '\r' || true)

existing_secretobjects=$(yq -r '
  .spec.secretObjects[].data[].objectName
' "$SPC_FILE" 2>/dev/null | tr -d '\r' || true)

obj_count=$(printf '%s\n' "$existing_objects" | grep -c '\S' || true)
sec_count=$(printf '%s\n' "$existing_secretobjects" | grep -c '\S' || true)
log_info "Found $obj_count existing SPC objects, $sec_count existing secretObjects"

# ─── Phase 1: Main loop ───────────────────────────────────────────────────────
log_phase "Phase 1 — Processing env vars"

while IFS= read -r name; do
  name=$(printf '%s' "$name" | tr -d '\r')
  [[ -z "$name" ]] && continue
  is_sensitive "$name" || continue

  safe_name=$(to_kv_name "$name")
  full_name="${PREFIX}-${safe_name}"

  echo -e "\n  ${BOLD}${name}${RESET}"
  log_info "KV name: $full_name"

  # Extract plaintext value (strip \r for Git Bash safety)
  raw_value=$(yq -r "
    .spec.template.spec.containers[].env[]
    | select(.name == \"$name\")
    | .value // \"\"
  " "$DEPLOYMENT_FILE" 2>/dev/null | head -1 | tr -d '\r')

  # ── 1a: Key Vault upload ──────────────────────────────────────────────────
  if [[ "$SKIP_KV" == false ]]; then

    if [[ -z "$raw_value" || "$raw_value" == "null" ]]; then
      log_warn "Value is empty or null — skipping KV upload"
      ((kv_empty++)) || true

    else
      kv_exists=false
      if az keyvault secret show \
          --vault-name "$VAULT_NAME" \
          --name "$full_name" \
          --output none 2>/dev/null; then
        kv_exists=true
      fi

      if [[ "$kv_exists" == true ]]; then
        log_skip "KV: $full_name already exists"
        ((kv_skipped++)) || true

      elif [[ "$DRY_RUN" == true ]]; then
        log_dryrun "Would upload $full_name (value length: ${#raw_value} chars)"

      else
        local_hash=$(safe_hash "$raw_value")

        if az keyvault secret set \
            --vault-name "$VAULT_NAME" \
            --name "$full_name" \
            --value "$raw_value" \
            --output none 2>/dev/null; then

          stored_value=$(az keyvault secret show \
            --vault-name "$VAULT_NAME" \
            --name "$full_name" \
            --query "value" -o tsv 2>/dev/null | tr -d '\r')

          stored_hash=$(safe_hash "$stored_value")

          kv_meta=$(az keyvault secret show \
            --vault-name "$VAULT_NAME" \
            --name "$full_name" \
            --query "{id:id,enabled:attributes.enabled,updated:attributes.updated}" \
            -o json 2>/dev/null)

          kv_version=$(printf '%s' "$kv_meta" | yq -r '.id' 2>/dev/null \
            | tr -d '\r' | rev | cut -d'/' -f1 | rev || echo "unknown")
          kv_updated=$(printf '%s' "$kv_meta" | yq -r '.updated' 2>/dev/null \
            | tr -d '\r' || echo "unknown")
          kv_enabled=$(printf '%s' "$kv_meta" | yq -r '.enabled' 2>/dev/null \
            | tr -d '\r' || echo "unknown")

          if [[ "$local_hash" == "$stored_hash" ]]; then
            log_ok "Uploaded and verified: $full_name"
            log_info "Version  : $kv_version"
            log_info "Updated  : $kv_updated"
            log_info "Enabled  : $kv_enabled"
            log_info "Checksum : ${local_hash:0:16}… ✔ matches"
            ((kv_uploaded++)) || true
          else
            log_err "Checksum MISMATCH for $full_name — stored value differs from source!"
            log_info "Local hash  : ${local_hash:0:16}…"
            log_info "Stored hash : ${stored_hash:0:16}…"
            ((kv_failed++)) || true
          fi

        else
          log_err "KV upload failed for $full_name"
          ((kv_failed++)) || true
        fi
      fi
    fi
  fi

  # ── 1b: Patch deployment ──────────────────────────────────────────────────
  if [[ "$SKIP_PATCH" == false ]]; then
    has_valueFrom=$(yq -r "
      .spec.template.spec.containers[].env[]
      | select(.name == \"$name\")
      | has(\"valueFrom\")
    " "$DEPLOYMENT_FILE" | head -1 | tr -d '\r')

    if [[ "$has_valueFrom" == "true" ]]; then
      log_skip "Deployment: $name already uses valueFrom"
    elif [[ "$DRY_RUN" == true ]]; then
      log_dryrun "Would patch deployment: $name → secretKeyRef:$full_name"
    else
      yq -i "
        (.spec.template.spec.containers[].env[] | select(.name == \"$name\"))
        |= {
          \"name\": .name,
          \"valueFrom\": {
            \"secretKeyRef\": {
              \"name\": \"$full_name\",
              \"key\": \"$full_name\"
            }
          }
        }
      " "$DEPLOYMENT_FILE"
      log_ok "Deployment patched: $name → secretKeyRef:$full_name"
      ((patch_deployment++)) || true
    fi
  fi

  # ── 1c: SPC objects block ─────────────────────────────────────────────────
  if [[ "$SKIP_PATCH" == false ]]; then
    if printf "%s\n" "$existing_objects" | grep -Fxq "$full_name"; then
      log_skip "SPC objects: $full_name"
    elif [[ "$DRY_RUN" == true ]]; then
      log_dryrun "Would add to SPC objects: $full_name"
    else
      cat >> "$tmp_objects" <<EOF
        - |
          objectName: $full_name
          objectType: secret
          objectVersion: ""
EOF
      existing_objects="${existing_objects}"$'\n'"${full_name}"
      log_ok "SPC objects queued: $full_name"
      ((patch_spc_objects++)) || true
    fi
  fi

  # ── 1d: SPC secretObjects ─────────────────────────────────────────────────
  if [[ "$SKIP_PATCH" == false ]]; then
    if printf "%s\n" "$existing_secretobjects" | grep -Fxq "$full_name"; then
      log_skip "SPC secretObjects: $full_name"
    elif [[ "$DRY_RUN" == true ]]; then
      log_dryrun "Would add to SPC secretObjects: $full_name"
    else
      yq -i "
        .spec.secretObjects += [{
          \"secretName\": \"$full_name\",
          \"type\": \"Opaque\",
          \"data\": [{
            \"key\": \"$full_name\",
            \"objectName\": \"$full_name\"
          }]
        }]
      " "$SPC_FILE"
      existing_secretobjects="${existing_secretobjects}"$'\n'"${full_name}"
      log_ok "SPC secretObjects added: $full_name"
      ((patch_spc_secretobjects++)) || true
    fi
  fi

done < <(yq -r '.spec.template.spec.containers[].env[].name' "$DEPLOYMENT_FILE" | tr -d '\r')

# ─── Phase 2: Flush SPC objects block ─────────────────────────────────────────
log_phase "Phase 2 — Flushing SPC objects block"

if [[ "$SKIP_PATCH" == false ]]; then
  if [[ -s "$tmp_objects" ]]; then
    if [[ "$DRY_RUN" == true ]]; then
      count=$(grep -c 'objectName' "$tmp_objects" || true)
      log_dryrun "Would append $count new entries to SPC objects block"
    else
      current=$(yq -r '.spec.parameters.objects // ""' "$SPC_FILE" | tr -d '\r')
      combined="${current}
$(cat "$tmp_objects")"
      export combined
      yq -i '.spec.parameters.objects = strenv(combined)' "$SPC_FILE"
      log_ok "SPC objects block updated"
    fi
  else
    log_skip "No new SPC objects to flush"
  fi
fi

# ─── Summary ──────────────────────────────────────────────────────────────────
log_phase "Summary"

echo -e "
  ${BOLD}Key Vault${RESET}
    ${GREEN}Uploaded${RESET}   : $kv_uploaded
    ${DIM}Skipped${RESET}    : $kv_skipped
    ${YELLOW}Empty/null${RESET} : $kv_empty
    ${RED}Failed${RESET}     : $kv_failed

  ${BOLD}SPC${RESET}
    Objects added        : $patch_spc_objects
    SecretObjects added  : $patch_spc_secretobjects

  ${BOLD}Deployment${RESET}
    Env vars patched     : $patch_deployment
"

[[ "$DRY_RUN" == true ]] && \
  echo -e "  ${YELLOW}Dry-run — no files were modified, no KV uploads made.${RESET}\n"

if [[ "$kv_failed" -gt 0 ]]; then
  log_err "$kv_failed secret(s) failed. Review logs above."
  exit 1
fi

echo -e "  ${GREEN}${BOLD}Done.${RESET}\n"
