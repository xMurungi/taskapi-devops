#!/usr/bin/env python3
# =============================================================================
# cluster-to-kv.py
# Reconciles Kubernetes secrets (cluster as source of truth) with Azure KV.
# Uses SPC secretObjects as the authoritative list of what should be in KV.
#
# Flow:
#   1. Select namespace(s) to scan
#   2. Read SPC files to discover expected secrets
#   3. Fetch each secret value from the cluster
#   4. Compare with KV — list missing, show mismatches visually
#   5. Confirm before uploading missing secrets to KV
#   6. Verify each upload before moving to next
#   7. Log everything (including plaintext) to a log file
#
# Usage:
#   python3 cluster-to-kv.py --vault ncba-core-test-kv [--dry-run] [--base-dir /path/to/apps/base]
#
# kubectl setup notes:
#   - Make sure kubectl is configured: kubectl config current-context
#   - To switch cluster: kubectl config use-context <context-name>
#   - To list contexts: kubectl config get-contexts
#   - To set namespace: kubectl config set-context --current --namespace=<ns>
#   - Verify access: kubectl get secrets -n <namespace>
#
# Add to .gitignore:
#   cluster-kv-audit-*.log
# =============================================================================

import sys
import os
import re
import json
import hashlib
import subprocess
import argparse
from datetime import datetime
from pathlib import Path

# ─── Colours ──────────────────────────────────────────────────────────────────
RED   = '\033[0;31m'
GRN   = '\033[0;32m'
CYN   = '\033[0;36m'
YEL   = '\033[1;33m'
BOLD  = '\033[1m'
DIM   = '\033[2m'
RST   = '\033[0m'

def phase(msg):   print(f"\n{BOLD}{CYN}══ {msg} ══{RST}")
def ok(msg):      print(f"  {GRN}✔{RST}  {msg}")
def skip(msg):    print(f"  {DIM}–{RST}  {msg}")
def err(msg):     print(f"  {RED}✘{RST}  {msg}", file=sys.stderr)
def info(msg):    print(f"  {DIM}→{RST}  {msg}")
def warn(msg):    print(f"  {YEL}⚠{RST}  {msg}")
def bold(msg):    print(f"  {BOLD}{msg}{RST}")

# ─── Log setup ────────────────────────────────────────────────────────────────
LOG_FILE = None

def setup_log():
    global LOG_FILE
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = Path(__file__).parent / f"cluster-kv-audit-{ts}.log"
    LOG_FILE = open(log_path, 'w', encoding='utf-8')
    log(f"cluster-to-kv.py audit log — {datetime.now().isoformat()}")
    log("=" * 80)
    print(f"\n  {DIM}Log file: {log_path}{RST}")
    return log_path

def log(msg, also_print=False):
    if LOG_FILE:
        LOG_FILE.write(msg + "\n")
        LOG_FILE.flush()
    if also_print:
        print(msg)

def log_section(title):
    log("")
    log("─" * 60)
    log(f"  {title}")
    log("─" * 60)

# ─── Shell helpers ────────────────────────────────────────────────────────────
def run(cmd, capture=True, check=False):
    result = subprocess.run(
        cmd, capture_output=capture, text=True
    )
    return result

def safe_hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()

# ─── kubectl helpers ──────────────────────────────────────────────────────────
def get_namespaces():
    result = run(["kubectl", "get", "namespaces", "-o", "jsonpath={.items[*].metadata.name}"])
    if result.returncode != 0:
        err("Failed to list namespaces. Is kubectl configured?")
        err(result.stderr)
        sys.exit(1)
    return result.stdout.strip().split()

def get_cluster_secret_value(secret_name, namespace):
    """Fetch a secret value from the cluster. Returns (value, error)."""
    result = run([
        "kubectl", "get", "secret", secret_name,
        "-n", namespace,
        "-o", f"jsonpath={{.data.{secret_name}}}"
    ])
    if result.returncode != 0:
        # Try with the key being the same as secret name
        result2 = run([
            "kubectl", "get", "secret", secret_name,
            "-n", namespace,
            "-o", "json"
        ])
        if result2.returncode != 0:
            return None, f"Secret not found in cluster: {secret_name} in {namespace}"

        try:
            data = json.loads(result2.stdout)
            secret_data = data.get("data", {})
            if not secret_data:
                return None, f"Secret exists but has no data: {secret_name}"

            # Try first key value
            import base64
            first_key = list(secret_data.keys())[0]
            value = base64.b64decode(secret_data[first_key]).decode('utf-8')
            return value, None
        except Exception as e:
            return None, str(e)

    if not result.stdout.strip():
        return None, f"Empty value for {secret_name}"

    import base64
    try:
        value = base64.b64decode(result.stdout.strip()).decode('utf-8')
        return value, None
    except Exception as e:
        return None, f"Failed to decode: {e}"

def secret_exists_in_cluster(secret_name, namespace):
    result = run(["kubectl", "get", "secret", secret_name, "-n", namespace])
    return result.returncode == 0

# ─── KV helpers ───────────────────────────────────────────────────────────────
kv_cache = {}

def kv_secret_exists(vault, name):
    if name in kv_cache:
        return kv_cache[name]['exists']
    result = run([
        "az", "keyvault", "secret", "show",
        "--vault-name", vault,
        "--name", name,
        "--query", "value", "-o", "tsv"
    ])
    exists = result.returncode == 0
    kv_cache[name] = {
        'exists': exists,
        'value': result.stdout.strip() if exists else None
    }
    return exists

def kv_get_value(vault, name):
    if name in kv_cache and kv_cache[name]['exists']:
        return kv_cache[name]['value']
    result = run([
        "az", "keyvault", "secret", "show",
        "--vault-name", vault,
        "--name", name,
        "--query", "value", "-o", "tsv"
    ])
    if result.returncode == 0:
        return result.stdout.strip()
    return None

def kv_set_value(vault, name, value):
    """Upload value to KV using file to handle values starting with -"""
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tmp:
        tmp.write(value)
        tmp_path = tmp.name
    try:
        result = run([
            "az", "keyvault", "secret", "set",
            "--vault-name", vault,
            "--name", name,
            "--file", tmp_path,
            "--output", "none"
        ])
        return result.returncode == 0, result.stderr
    finally:
        os.unlink(tmp_path)

def kv_get_metadata(vault, name):
    result = run([
        "az", "keyvault", "secret", "show",
        "--vault-name", vault,
        "--name", name,
        "--query", "{id:id,created:attributes.created,updated:attributes.updated,enabled:attributes.enabled}",
        "-o", "json"
    ])
    if result.returncode == 0:
        try:
            return json.loads(result.stdout)
        except:
            return {}
    return {}

# ─── SPC parsing ──────────────────────────────────────────────────────────────
def get_spc_secrets(spc_path):
    """
    Extract (secretName, objectName, namespace) from SPC secretObjects.
    Returns list of dicts.
    """
    with open(spc_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Get namespace from metadata
    ns_match = re.search(r'^\s+namespace:\s+(\S+)', content, re.MULTILINE)
    namespace = ns_match.group(1) if ns_match else None

    secrets = []
    # Match secretObjects entries
    # Pattern: secretName: X ... data: ... key: Y ... objectName: Z
    entries = re.finditer(
        r'- secretName:\s+(\S+)\s+type:\s+\S+\s+data:\s*\n(?:\s+.*\n)*?\s+objectName:\s+(\S+)',
        content
    )
    for m in entries:
        secret_name = m.group(1).strip()
        object_name = m.group(2).strip()
        secrets.append({
            'secretName': secret_name,
            'objectName': object_name,
            'namespace': namespace
        })

    return secrets, namespace

# ─── Visual comparison ────────────────────────────────────────────────────────
def show_comparison(secret_name, cluster_val, kv_val):
    print(f"\n  {BOLD}Visual comparison: {secret_name}{RST}")
    print(f"  {'─' * 60}")

    cluster_hash = safe_hash(cluster_val) if cluster_val else "N/A"
    kv_hash      = safe_hash(kv_val)      if kv_val      else "N/A"

    match = cluster_hash == kv_hash

    print(f"  {BOLD}Cluster value :{RST} {cluster_val}")
    print(f"  {BOLD}KV value      :{RST} {kv_val if kv_val else '[NOT IN KV]'}")
    print(f"  {BOLD}Cluster hash  :{RST} {cluster_hash[:24]}…")
    print(f"  {BOLD}KV hash       :{RST} {kv_hash[:24]}…")

    if match:
        print(f"  {GRN}✔ Values match{RST}")
    else:
        print(f"  {RED}✘ Values DO NOT match{RST}")

    print(f"  {'─' * 60}")
    return match

# ─── Prompt helpers ───────────────────────────────────────────────────────────
def ask(prompt, options=None):
    """Ask user a question. options like ['y','n','s']"""
    opts = f" [{'/'.join(options)}]" if options else ""
    while True:
        answer = input(f"\n  {YEL}?{RST}  {prompt}{opts}: ").strip().lower()
        if options is None or answer in options:
            return answer
        print(f"  Please enter one of: {', '.join(options)}")

def ask_namespace(all_namespaces):
    print(f"\n  {BOLD}Available namespaces:{RST}")
    for i, ns in enumerate(all_namespaces, 1):
        print(f"    {i}. {ns}")
    print(f"    0. All namespaces")

    while True:
        choice = input(f"\n  {YEL}?{RST}  Enter namespace number or name: ").strip()
        if choice == '0':
            return None  # all
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(all_namespaces):
                return [all_namespaces[idx]]
        except ValueError:
            if choice in all_namespaces:
                return [choice]
        print("  Invalid choice. Try again.")

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='Reconcile cluster secrets with Azure KV')
    parser.add_argument('--vault', required=True, help='Azure Key Vault name')
    parser.add_argument('--dry-run', action='store_true', help='Print what would happen, make no changes')
    parser.add_argument('--base-dir', default=None, help='Path to apps/base directory (default: auto-detect)')
    args = parser.parse_args()

    vault = args.vault
    dry_run = args.dry_run

    # Setup log
    log_path = setup_log()
    log(f"Vault    : {vault}")
    log(f"Dry run  : {dry_run}")

    if dry_run:
        print(f"\n  {YEL}{BOLD}DRY RUN MODE — no changes will be made{RST}")

    # Resolve base dir
    if args.base_dir:
        base_dir = Path(args.base_dir)
    else:
        script_dir = Path(__file__).parent.resolve()
        base_dir = script_dir / "apps" / "base"

    if not base_dir.exists():
        err(f"Base dir not found: {base_dir}")
        err("Use --base-dir to specify the path to apps/base")
        sys.exit(1)

    # ── Step 1: Namespace selection ────────────────────────────────────────────
    phase("Step 1 — Select namespace(s)")
    all_namespaces = get_namespaces()
    selected = ask_namespace(all_namespaces)
    target_namespaces = selected if selected else all_namespaces
    log(f"Target namespaces: {target_namespaces}")
    info(f"Scanning: {', '.join(target_namespaces) if selected else 'ALL namespaces'}")

    # ── Step 2: Discover SPC files ─────────────────────────────────────────────
    phase("Step 2 — Discovering SPC files")

    all_spc_secrets = []  # list of (svc, secret_dict)

    svc_dirs = sorted([d for d in base_dir.iterdir() if d.is_dir()])
    for svc_dir in svc_dirs:
        spc_path = svc_dir / "secretproviderclass.yaml"
        if not spc_path.exists():
            continue
        secrets, namespace = get_spc_secrets(spc_path)
        if not secrets:
            continue
        if namespace not in target_namespaces:
            continue
        for s in secrets:
            all_spc_secrets.append((svc_dir.name, s))

    info(f"Found {len(all_spc_secrets)} secret references across {len(set(s for s, _ in all_spc_secrets))} services")
    log(f"Total SPC secret references: {len(all_spc_secrets)}")

    # ── Step 3: Check each secret ──────────────────────────────────────────────
    phase("Step 3 — Checking secrets")

    missing_in_kv = []      # (svc, secret_dict, cluster_value)
    mismatch = []           # (svc, secret_dict, cluster_value, kv_value)
    matched = []            # (svc, secret_dict)
    not_in_cluster = []     # (svc, secret_dict)
    errors = []             # (svc, secret_dict, error_msg)

    total = len(all_spc_secrets)
    for i, (svc, s) in enumerate(all_spc_secrets, 1):
        secret_name = s['secretName']
        object_name = s['objectName']
        namespace   = s['namespace']

        print(f"\n  {BOLD}[{i}/{total}]{RST} {secret_name}")
        log_section(f"[{i}/{total}] {secret_name} (svc: {svc}, ns: {namespace})")

        # Get cluster value
        cluster_val, cluster_err = get_cluster_secret_value(secret_name, namespace)

        if cluster_err:
            warn(f"Not in cluster: {cluster_err}")
            log(f"  STATUS : NOT IN CLUSTER")
            log(f"  ERROR  : {cluster_err}")
            not_in_cluster.append((svc, s, cluster_err))
            continue

        log(f"  CLUSTER VALUE : {cluster_val}")
        log(f"  CLUSTER HASH  : {safe_hash(cluster_val)}")

        # Check KV
        kv_exists = kv_secret_exists(vault, object_name)

        if not kv_exists:
            warn(f"NOT in KV: {object_name}")
            log(f"  STATUS : MISSING FROM KV")
            log(f"  KV NAME: {object_name}")
            missing_in_kv.append((svc, s, cluster_val))
            continue

        # Both exist — compare
        kv_val = kv_get_value(vault, object_name)
        log(f"  KV VALUE      : {kv_val}")
        log(f"  KV HASH       : {safe_hash(kv_val) if kv_val else 'N/A'}")

        match = show_comparison(object_name, cluster_val, kv_val)

        if match:
            ok(f"Match: {object_name}")
            log(f"  STATUS : MATCH")
            matched.append((svc, s))
        else:
            warn(f"MISMATCH: {object_name}")
            log(f"  STATUS : MISMATCH")
            mismatch.append((svc, s, cluster_val, kv_val))

    # ── Step 4: Summary of findings ────────────────────────────────────────────
    phase("Step 4 — Findings summary")

    print(f"""
  {GRN}Matched (cluster = KV){RST}    : {len(matched)}
  {YEL}Missing from KV{RST}          : {len(missing_in_kv)}
  {YEL}Mismatch (values differ){RST} : {len(mismatch)}
  {DIM}Not in cluster{RST}           : {len(not_in_cluster)}
  {RED}Errors{RST}                   : {len(errors)}
""")

    log_section("SUMMARY")
    log(f"  Matched          : {len(matched)}")
    log(f"  Missing from KV  : {len(missing_in_kv)}")
    log(f"  Mismatch         : {len(mismatch)}")
    log(f"  Not in cluster   : {len(not_in_cluster)}")

    if missing_in_kv:
        log_section("MISSING FROM KV")
        print(f"\n  {BOLD}Secrets missing from KV:{RST}")
        for svc, s, cluster_val in missing_in_kv:
            print(f"    {RED}✘{RST} {s['objectName']}")
            print(f"      {DIM}Service: {svc} | Namespace: {s['namespace']}{RST}")
            log(f"  {s['objectName']} | cluster value: {cluster_val}")

    if mismatch:
        log_section("MISMATCHES")
        print(f"\n  {BOLD}Secrets with mismatched values:{RST}")
        for svc, s, cluster_val, kv_val in mismatch:
            print(f"    {YEL}≠{RST} {s['objectName']}")
            log(f"  {s['objectName']} | cluster: {cluster_val} | kv: {kv_val}")

    if dry_run:
        print(f"\n  {YEL}Dry run — stopping here. No changes made.{RST}\n")
        LOG_FILE.close()
        return

    # ── Step 5: Handle missing secrets ─────────────────────────────────────────
    if missing_in_kv:
        phase("Step 5 — Upload missing secrets to KV")

        answer = ask(
            f"Upload {len(missing_in_kv)} missing secret(s) to KV?",
            ['y', 'n']
        )

        if answer == 'y':
            for svc, s, cluster_val in missing_in_kv:
                object_name = s['objectName']
                print(f"\n  {BOLD}{object_name}{RST}")
                info(f"Cluster value : {cluster_val}")
                info(f"Cluster hash  : {safe_hash(cluster_val)[:24]}…")

                confirm = ask(f"Upload this secret to KV?", ['y', 'n', 's'])
                if confirm == 'n':
                    warn("Skipped by user")
                    log(f"  UPLOAD SKIPPED (user): {object_name}")
                    continue
                if confirm == 's':
                    warn("Skipped — will handle manually")
                    log(f"  UPLOAD SKIPPED (manual later): {object_name}")
                    continue

                # Upload
                success, upload_err = kv_set_value(vault, object_name, cluster_val)

                if not success:
                    err(f"Upload failed: {upload_err}")
                    log(f"  UPLOAD FAILED: {object_name} | error: {upload_err}")
                    pause = ask("Upload failed. Pause script or skip?", ['pause', 'skip'])
                    if pause == 'pause':
                        input("  Script paused. Press Enter to continue...")
                    continue

                # Verify
                info("Verifying upload…")
                kv_cache.pop(object_name, None)  # clear cache
                kv_val_after = kv_get_value(vault, object_name)

                match = show_comparison(object_name, cluster_val, kv_val_after)

                if match:
                    ok(f"Uploaded and verified: {object_name}")
                    meta = kv_get_metadata(vault, object_name)
                    version = meta.get('id', '').split('/')[-1] if meta else 'unknown'
                    info(f"KV version : {version}")
                    log(f"  UPLOADED OK: {object_name} | version: {version} | value: {cluster_val}")
                else:
                    err(f"Checksum mismatch after upload!")
                    log(f"  UPLOAD MISMATCH: {object_name} | cluster: {cluster_val} | kv_after: {kv_val_after}")
                    action = ask(
                        "Value mismatch after upload. Retry, skip, or pause?",
                        ['retry', 'skip', 'pause']
                    )
                    if action == 'retry':
                        kv_set_value(vault, object_name, cluster_val)
                        ok("Retried — check logs")
                    elif action == 'pause':
                        input("  Script paused. Press Enter to continue...")

    # ── Step 6: Handle mismatches ──────────────────────────────────────────────
    if mismatch:
        phase("Step 6 — Handle mismatched secrets")
        warn("The following secrets exist in both cluster and KV but values differ.")
        warn("Cluster is source of truth — uploading cluster value will overwrite KV.")

        for svc, s, cluster_val, kv_val in mismatch:
            object_name = s['objectName']
            print(f"\n  {BOLD}{object_name}{RST}")
            show_comparison(object_name, cluster_val, kv_val)

            action = ask(
                "Overwrite KV with cluster value, skip, or pause?",
                ['overwrite', 'skip', 'pause']
            )

            if action == 'skip':
                log(f"  MISMATCH SKIPPED: {object_name}")
                continue
            if action == 'pause':
                input("  Script paused. Press Enter to continue...")
                log(f"  MISMATCH PAUSED: {object_name}")
                continue

            success, upload_err = kv_set_value(vault, object_name, cluster_val)
            if not success:
                err(f"Upload failed: {upload_err}")
                log(f"  OVERWRITE FAILED: {object_name} | error: {upload_err}")
                continue

            kv_cache.pop(object_name, None)
            kv_val_after = kv_get_value(vault, object_name)
            match = show_comparison(object_name, cluster_val, kv_val_after)

            if match:
                ok(f"Overwritten and verified: {object_name}")
                log(f"  OVERWRITTEN OK: {object_name} | value: {cluster_val}")
            else:
                err(f"Still mismatched after overwrite!")
                log(f"  OVERWRITE MISMATCH: {object_name}")

    # ── Final summary ──────────────────────────────────────────────────────────
    phase("Done")
    print(f"  {GRN}{BOLD}Reconciliation complete.{RST}")
    print(f"  {DIM}Full log: {log_path}{RST}\n")
    log("")
    log("=" * 80)
    log("RECONCILIATION COMPLETE")
    LOG_FILE.close()


if __name__ == "__main__":
    main()
