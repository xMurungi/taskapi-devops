#!/usr/bin/env python3
# =============================================================================
# fix-404-secrets.py
# For each service, checks every objectName in the SPC objects block against
# Azure Key Vault. If a secret returns 404, removes it from:
#   - SPC objects block (the - | / objectName / objectType / objectVersion block)
#   - SPC secretObjects (the matching secretName entry)
#   - Deployment (the valueFrom block only — name: line is preserved as-is)
#
# No indentation changes. No whitespace changes. Nothing else touched.
#
# Usage (run from inside repo folder):
#   python3 fix-404-secrets.py
#
# Works on Mac and Windows Git Bash.
# =============================================================================

import sys
import re
import shutil
import subprocess
from pathlib import Path

RED  = '\033[0;31m'
GRN  = '\033[0;32m'
CYN  = '\033[0;36m'
YEL  = '\033[1;33m'
BOLD = '\033[1m'
DIM  = '\033[2m'
RST  = '\033[0m'

def phase(msg): print(f"\n{BOLD}{CYN}══ {msg} ══{RST}")
def ok(msg):    print(f"  {GRN}✔{RST}  {msg}")
def skip(msg):  print(f"  {DIM}–{RST}  {msg} {DIM}(skipped){RST}")
def err(msg):   print(f"  {RED}✘{RST}  {msg}", file=sys.stderr)
def info(msg):  print(f"  {DIM}→{RST}  {msg}")
def warn(msg):  print(f"  {YEL}⚠{RST}  {msg}")

VAULT = "ncba-core-test-kv"

# ─── KV check ─────────────────────────────────────────────────────────────────
kv_cache = {}  # cache results to avoid repeat az calls

def secret_exists_in_kv(secret_name):
    if secret_name in kv_cache:
        return kv_cache[secret_name]
    try:
        result = subprocess.run(
            ["az", "keyvault", "secret", "show",
             "--vault-name", VAULT,
             "--name", secret_name,
             "--query", "name", "-o", "tsv"],
            capture_output=True, text=True
        )
        exists = result.returncode == 0
        kv_cache[secret_name] = exists
        return exists
    except Exception:
        kv_cache[secret_name] = True  # assume exists on error, don't remove
        return True

# ─── SPC fix ──────────────────────────────────────────────────────────────────
def fix_spc(spc_path, missing_secrets):
    """
    Remove entries for missing_secrets from:
      - objects block (- | / objectName / objectType / objectVersion)
      - secretObjects entries (entire secretName block)
    No other changes.
    """
    with open(spc_path, 'r', encoding='utf-8') as f:
        content = f.read()

    original = content

    # ── Remove from objects block ─────────────────────────────────────────────
    # Each entry looks like (preserving exact original spacing):
    #         - |
    #           objectName: some-name
    #           objectType: secret
    #           objectVersion: ""
    # We match the block starting at "- |" and ending after objectVersion line
    # We do NOT touch indentation — just remove the matched lines exactly

    for secret in missing_secrets:
        # Match the block for this specific secret in the objects block
        # Pattern: any indent + "- |" + newline + same-or-more indent + "objectName: <secret>" + rest of block
        pattern = re.compile(
            r'( *- \|\n *objectName: ' + re.escape(secret) + r'\n *objectType: secret\n *objectVersion: "[^"]*"\n?)',
            re.MULTILINE
        )
        new_content = pattern.sub('', content)
        if new_content != content:
            content = new_content

    # ── Remove from secretObjects ─────────────────────────────────────────────
    # Each secretObjects entry looks like:
    #     - secretName: some-name
    #       type: Opaque
    #       data:
    #         - key: some-name
    #           objectName: some-name
    # We match by objectName inside data block

    for secret in missing_secrets:
        # Match entire secretObjects entry containing this objectName
        # The entry starts with "    - secretName:" and ends before next "    - secretName:" or "  provider:"
        pattern = re.compile(
            r'( +- secretName: [^\n]+\n +type: Opaque\n +data:\n(?:.*\n)*?.*objectName: '
            + re.escape(secret) + r'\n)',
            re.MULTILINE
        )
        new_content = pattern.sub('', content)
        if new_content != content:
            content = new_content

    if content == original:
        return False

    with open(spc_path, 'w', encoding='utf-8') as f:
        f.write(content)

    return True

# ─── Deployment fix ───────────────────────────────────────────────────────────
def fix_deployment(dep_path, missing_secrets):
    """
    For env vars whose secretKeyRef name is in missing_secrets:
    Remove the valueFrom block entirely. Leave the name: line untouched.
    Do not add value: or anything else — just remove valueFrom.
    """
    with open(dep_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    original = ''.join(lines)
    output = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Look for valueFrom block
        if line.strip() == 'valueFrom:':
            # Check if the secretKeyRef name is in missing_secrets
            # Look ahead for secretKeyRef name
            block_lines = [line]
            j = i + 1
            found_missing = False

            while j < len(lines):
                next_line = lines[j]
                block_lines.append(next_line)

                # Check if this is the name: line inside secretKeyRef
                m = re.match(r'\s+name:\s+(\S+)', next_line)
                if m:
                    ref_name = m.group(1)
                    if ref_name in missing_secrets:
                        found_missing = True

                # Stop at next env var or end of valueFrom block
                stripped = next_line.strip()
                if stripped.startswith('- name:') or (
                    next_line[0] != ' ' and stripped
                ):
                    break

                # End of valueFrom block — key: line ends it
                if stripped.startswith('key:'):
                    j += 1
                    break

                j += 1

            if found_missing:
                # Skip the entire valueFrom block — don't write block_lines
                i = j
                continue
            else:
                # Not a missing secret — write normally
                output.append(line)
                i += 1
                continue

        output.append(line)
        i += 1

    new_content = ''.join(output)

    if new_content == original:
        return False

    with open(dep_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

    return True

# ─── Get objectNames from SPC ─────────────────────────────────────────────────
def get_object_names(spc_path):
    """Extract all objectName values from the SPC objects block."""
    with open(spc_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find all objectName: values in the objects block
    # Works for both multiline and one-liner (escaped) formats
    names = []

    # Multiline format
    for m in re.finditer(r'objectName:\s+(\S+)', content):
        name = m.group(1).strip()
        if name and name not in names:
            names.append(name)

    # One-liner escaped format
    for m in re.finditer(r'objectName:\\s*([^\\]+?)\\n', content):
        name = m.group(1).strip()
        if name and name not in names:
            names.append(name)

    return names

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    script_dir = Path(__file__).parent.resolve()
    base_dir = script_dir / "apps" / "base"

    if not base_dir.exists():
        err(f"Base dir not found: {base_dir}")
        sys.exit(1)

    # Discover all service folders
    services = sorted([
        d.name for d in base_dir.iterdir()
        if d.is_dir() and (d / "secretproviderclass.yaml").exists()
    ])

    phase(f"Checking {len(services)} services against KV ({VAULT})")

    total_checked = 0
    total_missing = 0
    total_spc_fixed = 0
    total_dep_fixed = 0
    total_failed = 0

    for i, svc in enumerate(services, 1):
        svc_dir = base_dir / svc
        spc_path = svc_dir / "secretproviderclass.yaml"
        dep_path = svc_dir / "deployment.yaml"

        print(f"\n  {BOLD}[{i}/{len(services)}] {svc}{RST}")

        # Get all objectNames from SPC
        object_names = get_object_names(spc_path)

        if not object_names:
            skip(f"No objectNames found in SPC")
            continue

        # Check each against KV
        missing = []
        for name in object_names:
            total_checked += 1
            if not secret_exists_in_kv(name):
                warn(f"404: {name}")
                missing.append(name)
                total_missing += 1
            else:
                pass  # silent for ok ones to keep output clean

        if not missing:
            ok(f"All {len(object_names)} secrets exist in KV")
            continue

        info(f"{len(missing)} missing secret(s) to remove")

        # Backup both files before touching
        spc_backup = Path(str(spc_path) + ".bak")
        dep_backup = Path(str(dep_path) + ".bak") if dep_path.exists() else None

        shutil.copy2(spc_path, spc_backup)
        if dep_path.exists() and dep_backup:
            shutil.copy2(dep_path, dep_backup)

        try:
            # Fix SPC
            spc_changed = fix_spc(spc_path, missing)
            if spc_changed:
                ok(f"SPC cleaned — removed {len(missing)} entr{'y' if len(missing) == 1 else 'ies'}")
                total_spc_fixed += 1
            else:
                warn(f"SPC — no changes made (entries may already be absent)")
            spc_backup.unlink(missing_ok=True)

            # Fix deployment
            if dep_path.exists():
                dep_changed = fix_deployment(dep_path, missing)
                if dep_changed:
                    ok(f"Deployment cleaned — removed valueFrom refs")
                    total_dep_fixed += 1
                else:
                    info(f"Deployment — no valueFrom refs found for missing secrets")
                if dep_backup:
                    dep_backup.unlink(missing_ok=True)

        except Exception as e:
            err(f"{svc} — exception: {e}")
            if spc_backup.exists():
                shutil.move(str(spc_backup), str(spc_path))
            if dep_backup and dep_backup.exists():
                shutil.move(str(dep_backup), str(dep_path))
            total_failed += 1

    phase("Summary")
    print(f"""
  Secrets checked          : {total_checked}
  {RED}404 secrets found{RST}        : {total_missing}
  {GRN}SPC files cleaned{RST}        : {total_spc_fixed}
  {GRN}Deployment files cleaned{RST} : {total_dep_fixed}
  {RED}Failed{RST}                   : {total_failed}
""")

    if total_failed > 0:
        err(f"{total_failed} service(s) failed — backups restored")
        sys.exit(1)

    print(f"  {GRN}{BOLD}All done.{RST}\n")


if __name__ == "__main__":
    main()
