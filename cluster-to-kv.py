#!/usr/bin/env python3
# =============================================================================
# cluster-to-kv.py
# Reconciles Kubernetes secrets (cluster as source of truth) with Azure KV.
# Uses kubectl directly — no SPC files, no deployment manifests.
#
# Flow:
#   1. Show current kubectl context — confirm you're on the right cluster
#   2. Select namespace(s) to scan
#   3. kubectl get secrets — list all non-system secrets
#   4. For each secret key, check if it exists in KV by the same name
#   5. Compare values via checksum — show visual diff in terminal
#   6. List missing — confirm before uploading to KV
#   7. Log everything (including plaintext values) to a log file
#
# Usage:
#   python3 cluster-to-kv.py --vault ncba-core-test-kv [--dry-run]
#
# kubectl setup notes:
#   - Check current context : kubectl config current-context
#   - List contexts         : kubectl config get-contexts
#   - Switch context        : kubectl config use-context <context-name>
#   - Verify access         : kubectl get secrets -n <namespace>
#
# Add to .gitignore:
#   cluster-kv-audit-*.log
# =============================================================================

import sys
import os
import re
import json
import base64
import hashlib
import tempfile
import platform
import subprocess
import argparse
from datetime import datetime
from pathlib import Path

# ─── Platform-aware az command ────────────────────────────────────────────────
AZ_CMD = "az.cmd" if platform.system() == "Windows" else "az"

# ─── Colours ──────────────────────────────────────────────────────────────────
RED   = '\033[0;31m'
GRN   = '\033[0;32m'
CYN   = '\033[0;36m'
YEL   = '\033[1;33m'
BOLD  = '\033[1m'
DIM   = '\033[2m'
RST   = '\033[0m'

def phase(msg): print(f"\n{BOLD}{CYN}══ {msg} ══{RST}")
def ok(msg):    print(f"  {GRN}✔{RST}  {msg}")
def skip(msg):  print(f"  {DIM}–{RST}  {msg} {DIM}(skipped){RST}")
def err(msg):   print(f"  {RED}✘{RST}  {msg}", file=sys.stderr)
def info(msg):  print(f"  {DIM}→{RST}  {msg}")
def warn(msg):  print(f"  {YEL}⚠{RST}  {msg}")

# ─── Log setup ────────────────────────────────────────────────────────────────
LOG_FILE = None

def setup_log():
    global LOG_FILE
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = Path(__file__).parent / f"cluster-kv-audit-{ts}.log"
    LOG_FILE = open(log_path, 'w', encoding='utf-8')
    log(f"cluster-to-kv.py — {datetime.now().isoformat()}")
    log("=" * 80)
    print(f"\n  {DIM}Log file: {log_path}{RST}")
    return log_path

def log(msg):
    if LOG_FILE:
        LOG_FILE.write(msg + "\n")
        LOG_FILE.flush()

def log_section(title):
    log("")
    log("─" * 60)
    log(f"  {title}")
    log("─" * 60)

# ─── Shell helper ─────────────────────────────────────────────────────────────
def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)

def safe_hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()

# ─── System secret detection ──────────────────────────────────────────────────
SKIP_TYPES = {
    "kubernetes.io/service-account-token",
    "kubernetes.io/dockerconfigjson",
    "kubernetes.io/dockercfg",
    "helm.sh/release.v1",
    "bootstrap.kubernetes.io/token",
}

SKIP_NAME_PATTERNS = [
    r'^sh\.helm\.release',
    r'-token-[a-z0-9]+$',
    r'^secrets-store-creds$',
    r'^flux-acr-password$',
    r'^default-token',
]

def is_system_secret(name, secret_type):
    if secret_type in SKIP_TYPES:
        return True
    for pattern in SKIP_NAME_PATTERNS:
        if re.search(pattern, name):
            return True
    return False

# ─── kubectl helpers ──────────────────────────────────────────────────────────
def get_current_context():
    result = run(["kubectl", "config", "current-context"])
    if result.returncode != 0:
        err("Failed to get kubectl context. Is kubectl configured?")
        sys.exit(1)
    return result.stdout.strip()

def get_namespaces():
    result = run(["kubectl", "get", "namespaces",
                  "-o", "jsonpath={.items[*].metadata.name}"])
    if result.returncode != 0:
        err("Failed to list namespaces.")
        err(result.stderr)
        sys.exit(1)
    return result.stdout.strip().split()

def get_secrets_in_namespace(namespace):
    result = run(["kubectl", "get", "secrets",
                  "-n", namespace, "-o", "json"])
    if result.returncode != 0:
        err(f"Failed to list secrets in {namespace}: {result.stderr}")
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        err(f"Failed to parse kubectl output for {namespace}")
        return []

    secrets = []
    for item in data.get("items", []):
        name        = item["metadata"]["name"]
        secret_type = item.get("type", "Opaque")
        raw_data    = item.get("data", {})

        if is_system_secret(name, secret_type):
            continue

        secrets.append({
            "name":     name,
            "type":     secret_type,
            "keys":     list(raw_data.keys()),
            "raw_data": raw_data,
            "namespace": namespace,
        })

    return secrets

def decode_secret_value(b64_value):
    try:
        return base64.b64decode(b64_value).decode('utf-8')
    except Exception:
        return None

# ─── KV helpers ───────────────────────────────────────────────────────────────
kv_cache = {}

def kv_secret_exists(vault, name):
    if name in kv_cache:
        return kv_cache[name]['exists']
    result = run([AZ_CMD, "keyvault", "secret", "show",
                  "--vault-name", vault,
                  "--name", name,
                  "--query", "value", "-o", "tsv"])
    exists = result.returncode == 0
    kv_cache[name] = {
        'exists': exists,
        'value': result.stdout.strip() if exists else None
    }
    return exists

def kv_get_value(vault, name):
    if name in kv_cache and kv_cache[name]['exists']:
        return kv_cache[name]['value']
    result = run([AZ_CMD, "keyvault", "secret", "show",
                  "--vault-name", vault,
                  "--name", name,
                  "--query", "value", "-o", "tsv"])
    if result.returncode == 0:
        return result.stdout.strip()
    return None

def kv_set_value(vault, name, value):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt',
                                     delete=False, encoding='utf-8') as tmp:
        tmp.write(value)
        tmp_path = tmp.name
    try:
        result = run([AZ_CMD, "keyvault", "secret", "set",
                      "--vault-name", vault,
                      "--name", name,
                      "--file", tmp_path,
                      "--output", "none"])
        return result.returncode == 0, result.stderr
    finally:
        os.unlink(tmp_path)

def kv_get_metadata(vault, name):
    result = run([AZ_CMD, "keyvault", "secret", "show",
                  "--vault-name", vault, "--name", name,
                  "--query",
                  "{id:id,created:attributes.created,updated:attributes.updated}",
                  "-o", "json"])
    if result.returncode == 0:
        try:
            return json.loads(result.stdout)
        except Exception:
            return {}
    return {}

# ─── Visual comparison ────────────────────────────────────────────────────────
def show_comparison(name, cluster_val, kv_val):
    print(f"\n  {BOLD}{'─' * 60}{RST}")
    print(f"  {BOLD}Secret       :{RST} {name}")
    print(f"  {BOLD}Cluster value:{RST} {cluster_val}")
    print(f"  {BOLD}KV value     :{RST} {kv_val if kv_val else '[NOT IN KV]'}")

    c_hash = safe_hash(cluster_val) if cluster_val else "N/A"
    k_hash = safe_hash(kv_val)      if kv_val      else "N/A"

    print(f"  {BOLD}Cluster hash :{RST} {c_hash[:32]}…")
    print(f"  {BOLD}KV hash      :{RST} {k_hash[:32]}…")

    match = c_hash == k_hash
    print(f"  {GRN}✔ Match{RST}" if match else f"  {RED}✘ Mismatch{RST}")
    print(f"  {BOLD}{'─' * 60}{RST}")
    return match

# ─── Prompt helpers ───────────────────────────────────────────────────────────
def ask(prompt, options):
    opts = f" [{'/'.join(options)}]"
    while True:
        answer = input(f"\n  {YEL}?{RST}  {prompt}{opts}: ").strip().lower()
        if answer in options:
            return answer
        print(f"  Please enter one of: {', '.join(options)}")

def ask_namespace(all_namespaces):
    print(f"\n  {BOLD}Available namespaces:{RST}")
    for i, ns in enumerate(all_namespaces, 1):
        print(f"    {i:3}. {ns}")
    print(f"      0. All namespaces")

    while True:
        choice = input(f"\n  {YEL}?{RST}  Enter number or namespace name: ").strip()
        if choice == '0':
            return None
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(all_namespaces):
                return [all_namespaces[idx]]
        except ValueError:
            if choice in all_namespaces:
                return [choice]
        print("  Invalid. Try again.")

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description='Reconcile Kubernetes secrets with Azure Key Vault'
    )
    parser.add_argument('--vault', required=True, help='Azure Key Vault name')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would happen — make no changes')
    args = parser.parse_args()

    vault   = args.vault
    dry_run = args.dry_run

    log_path = setup_log()
    log(f"Vault   : {vault}")
    log(f"Dry run : {dry_run}")

    if dry_run:
        print(f"\n  {YEL}{BOLD}DRY RUN — no changes will be made{RST}")

    # ── Step 1: Confirm kubectl context ───────────────────────────────────────
    phase("Step 1 — kubectl context")
    context = get_current_context()
    print(f"\n  {BOLD}Current context:{RST} {CYN}{context}{RST}")
    log(f"kubectl context: {context}")

    confirm = ask("Is this the correct cluster?", ['y', 'n'])
    if confirm == 'n':
        print("\n  Run: kubectl config use-context <context-name>")
        print("  List contexts: kubectl config get-contexts")
        sys.exit(0)

    # ── Step 2: Namespace selection ───────────────────────────────────────────
    phase("Step 2 — Select namespace(s)")
    all_namespaces = get_namespaces()
    selected = ask_namespace(all_namespaces)
    target_namespaces = selected if selected else all_namespaces
    log(f"Namespaces: {target_namespaces}")
    info(f"Scanning: {', '.join(target_namespaces) if selected else 'ALL namespaces'}")

    # ── Step 3: Collect secrets from cluster ──────────────────────────────────
    phase("Step 3 — Collecting secrets from cluster")

    all_entries = []

    for ns in target_namespaces:
        info(f"Scanning namespace: {ns}")
        secrets = get_secrets_in_namespace(ns)
        skipped_count = 0

        ns_result = run(["kubectl", "get", "secrets", "-n", ns, "-o", "json"])
        try:
            ns_data = json.loads(ns_result.stdout)
            total_in_ns = len(ns_data.get("items", []))
            skipped_count = total_in_ns - len(secrets)
        except Exception:
            pass

        info(f"  Found {len(secrets)} app secret(s), skipped {skipped_count} system secret(s)")

        for secret in secrets:
            for key in secret['keys']:
                raw_val = secret['raw_data'].get(key, '')
                decoded = decode_secret_value(raw_val) if raw_val else None
                all_entries.append({
                    'namespace':     ns,
                    'secret_name':   secret['name'],
                    'key':           key,
                    'cluster_value': decoded,
                    'kv_name':       key,
                })

    info(f"Total secret keys to check: {len(all_entries)}")
    log(f"Total entries: {len(all_entries)}")

    if not all_entries:
        warn("No secrets found to check.")
        LOG_FILE.close()
        return

    # ── Step 4: Check each against KV ────────────────────────────────────────
    phase("Step 4 — Checking against Key Vault")

    missing_in_kv = []
    mismatched    = []
    matched       = []
    decode_errors = []

    total = len(all_entries)

    for i, entry in enumerate(all_entries, 1):
        ns          = entry['namespace']
        secret_name = entry['secret_name']
        key         = entry['key']
        kv_name     = entry['kv_name']
        cluster_val = entry['cluster_value']

        print(f"\n  {BOLD}[{i}/{total}]{RST} {kv_name}  {DIM}(ns: {ns}){RST}")

        log_section(f"[{i}/{total}] {kv_name}")
        log(f"  Namespace   : {ns}")
        log(f"  Secret name : {secret_name}")
        log(f"  Key         : {key}")

        if cluster_val is None:
            warn("Could not decode cluster value — skipping")
            log(f"  STATUS: DECODE ERROR")
            decode_errors.append(entry)
            continue

        log(f"  CLUSTER VALUE : {cluster_val}")
        log(f"  CLUSTER HASH  : {safe_hash(cluster_val)}")

        exists = kv_secret_exists(vault, kv_name)

        if not exists:
            warn(f"NOT in KV")
            log(f"  STATUS: MISSING FROM KV")
            missing_in_kv.append(entry)
            continue

        kv_val = kv_get_value(vault, kv_name)
        log(f"  KV VALUE      : {kv_val}")
        log(f"  KV HASH       : {safe_hash(kv_val) if kv_val else 'N/A'}")

        match = show_comparison(kv_name, cluster_val, kv_val)

        if match:
            log(f"  STATUS: MATCH")
            matched.append(entry)
        else:
            log(f"  STATUS: MISMATCH")
            mismatched.append({**entry, 'kv_value': kv_val})

    # ── Step 5: Summary ───────────────────────────────────────────────────────
    phase("Step 5 — Summary")

    print(f"""
  {GRN}Matched (cluster = KV){RST}    : {len(matched)}
  {YEL}Missing from KV{RST}          : {len(missing_in_kv)}
  {YEL}Mismatch (values differ){RST} : {len(mismatched)}
  {DIM}Decode errors (skipped){RST}  : {len(decode_errors)}
""")

    log_section("SUMMARY")
    log(f"  Matched        : {len(matched)}")
    log(f"  Missing from KV: {len(missing_in_kv)}")
    log(f"  Mismatch       : {len(mismatched)}")
    log(f"  Decode errors  : {len(decode_errors)}")

    if missing_in_kv:
        print(f"\n  {BOLD}Missing from KV:{RST}")
        log_section("MISSING FROM KV")
        for e in missing_in_kv:
            print(f"    {RED}✘{RST} {e['kv_name']}  {DIM}(ns: {e['namespace']}){RST}")
            log(f"  {e['kv_name']} | ns: {e['namespace']} | cluster value: {e['cluster_value']}")

    if mismatched:
        print(f"\n  {BOLD}Mismatched:{RST}")
        log_section("MISMATCHES")
        for e in mismatched:
            print(f"    {YEL}≠{RST} {e['kv_name']}  {DIM}(ns: {e['namespace']}){RST}")
            log(f"  {e['kv_name']} | cluster: {e['cluster_value']} | kv: {e['kv_value']}")

    if dry_run:
        print(f"\n  {YEL}Dry run — stopping here. No changes made.{RST}\n")
        LOG_FILE.close()
        return

    # ── Step 6: Upload missing secrets ────────────────────────────────────────
    if missing_in_kv:
        phase("Step 6 — Upload missing secrets to KV")

        answer = ask(
            f"Upload {len(missing_in_kv)} missing secret(s) to KV?",
            ['y', 'n']
        )

        if answer == 'y':
            for entry in missing_in_kv:
                kv_name     = entry['kv_name']
                cluster_val = entry['cluster_value']

                print(f"\n  {BOLD}{kv_name}{RST}")
                info(f"Cluster value : {cluster_val}")
                info(f"Cluster hash  : {safe_hash(cluster_val)[:32]}…")

                confirm = ask("Upload this secret?", ['y', 'skip', 'pause'])
                if confirm == 'skip':
                    warn("Skipped")
                    log(f"  UPLOAD SKIPPED: {kv_name}")
                    continue
                if confirm == 'pause':
                    input("  Paused. Press Enter to continue...")
                    log(f"  UPLOAD PAUSED: {kv_name}")
                    continue

                success, upload_err = kv_set_value(vault, kv_name, cluster_val)

                if not success:
                    err(f"Upload failed: {upload_err}")
                    log(f"  UPLOAD FAILED: {kv_name} | error: {upload_err}")
                    action = ask("Upload failed. Pause or skip?", ['pause', 'skip'])
                    if action == 'pause':
                        input("  Paused. Press Enter to continue...")
                    continue

                info("Verifying…")
                kv_cache.pop(kv_name, None)
                kv_val_after = kv_get_value(vault, kv_name)
                match = show_comparison(kv_name, cluster_val, kv_val_after)

                if match:
                    meta    = kv_get_metadata(vault, kv_name)
                    version = meta.get('id', '').split('/')[-1] if meta else 'unknown'
                    ok(f"Uploaded and verified")
                    info(f"KV version: {version}")
                    log(f"  UPLOADED OK: {kv_name} | version: {version} | value: {cluster_val}")
                else:
                    err("Checksum mismatch after upload!")
                    log(f"  UPLOAD MISMATCH: {kv_name}")
                    action = ask("Mismatch after upload. Retry, skip, or pause?",
                                 ['retry', 'skip', 'pause'])
                    if action == 'retry':
                        kv_set_value(vault, kv_name, cluster_val)
                        ok("Retried — check logs")
                        log(f"  RETRIED: {kv_name}")
                    elif action == 'pause':
                        input("  Paused. Press Enter to continue...")

    # ── Step 7: Handle mismatches ─────────────────────────────────────────────
    if mismatched:
        phase("Step 7 — Handle mismatched secrets")
        warn("These secrets exist in both cluster and KV but values differ.")
        warn("Cluster is source of truth.")

        for entry in mismatched:
            kv_name     = entry['kv_name']
            cluster_val = entry['cluster_value']
            kv_val      = entry['kv_value']

            print(f"\n  {BOLD}{kv_name}{RST}")
            show_comparison(kv_name, cluster_val, kv_val)

            action = ask("Overwrite KV with cluster value, skip, or pause?",
                         ['overwrite', 'skip', 'pause'])

            if action == 'skip':
                log(f"  MISMATCH SKIPPED: {kv_name}")
                continue
            if action == 'pause':
                input("  Paused. Press Enter to continue...")
                log(f"  MISMATCH PAUSED: {kv_name}")
                continue

            success, upload_err = kv_set_value(vault, kv_name, cluster_val)
            if not success:
                err(f"Upload failed: {upload_err}")
                log(f"  OVERWRITE FAILED: {kv_name} | error: {upload_err}")
                continue

            kv_cache.pop(kv_name, None)
            kv_val_after = kv_get_value(vault, kv_name)
            match = show_comparison(kv_name, cluster_val, kv_val_after)

            if match:
                ok("Overwritten and verified")
                log(f"  OVERWRITTEN OK: {kv_name} | value: {cluster_val}")
            else:
                err("Still mismatched after overwrite!")
                log(f"  OVERWRITE MISMATCH: {kv_name}")

    # ── Done ──────────────────────────────────────────────────────────────────
    phase("Done")
    print(f"  {GRN}{BOLD}Reconciliation complete.{RST}")
    print(f"  {DIM}Full log: {log_path}{RST}\n")
    log("")
    log("=" * 80)
    log("RECONCILIATION COMPLETE")
    LOG_FILE.close()


if __name__ == "__main__":
    main()
