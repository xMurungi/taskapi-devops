#!/usr/bin/env python3
# =============================================================================
# fix-spc-indentation.py
# Re-indents over-indented entries in SPC objects blocks.
# Bad entries have 14 spaces before "- |" and 16 before objectName etc.
# Correct entries have 8 spaces before "- |" and 10 before objectName etc.
# Fix: shift bad lines left by 6 spaces.
# Only touches secretproviderclass.yaml — no other files modified.
#
# Usage (run from inside repo folder):
#   python3 fix-spc-indentation.py
#
# Works on Mac and Windows Git Bash.
# =============================================================================

import sys
import shutil
from pathlib import Path

# ─── Colours ──────────────────────────────────────────────────────────────────
RED  = '\033[0;31m'
GRN  = '\033[0;32m'
CYN  = '\033[0;36m'
BOLD = '\033[1m'
DIM  = '\033[2m'
RST  = '\033[0m'

def phase(msg): print(f"\n{BOLD}{CYN}══ {msg} ══{RST}")
def ok(msg):    print(f"  {GRN}✔{RST}  {msg}")
def skip(msg):  print(f"  {DIM}–{RST}  {msg} {DIM}(skipped){RST}")
def err(msg):   print(f"  {RED}✘{RST}  {msg}", file=sys.stderr)
def info(msg):  print(f"  {DIM}→{RST}  {msg}")

# ─── Services to fix ──────────────────────────────────────────────────────────
SERVICES = [
    "ncbakemobilemoneyapi-mtech-adapter",
    "ncbanotificationsservice-coreapi-api",
    "ncbarwbillersapi-coreapi-api",
    "ncbarwmobilemoneyapi-airteladapter-api",
    "ncbarwmobilemoneyapi-ekash-callback",
    "ncbarwmobilemoneyapi-mtnadapter-api",
    "ncbatzbillersapi-cellulant-backgroundtasks",
    "ncbatzbillersapi-cellulantadapter",
    "ncbatzbillersapi-cellulantcallback",
    "ncbatzbillersapi-coreapi-api",
    "ncbatzbillersapi-coreapi-backgroundtasks",
    "ncbatzbillersapi-gepg-backgroundtasks",
    "ncbatzbillersapi-gepgadapter",
    "ncbatzbillersapi-gepgcallback",
    "ncbatzbillersapi-selcom-backgroundtasks",
    "ncbatzbillersapi-selcomadapter",
    "ncbatzbillersapi-tips-backgroundtasks",
    "ncbatzmobilemoneyapi-coreapi-api",
    "ncbatzmobilemoneyapi-coreapi-backgroundtasks",
    "ncbatzmobilemoneyapi-selcom-backgroundtasks",
    "ncbatzmobilemoneyapi-selcomadapter",
    "ncbatzmobilemoneyapi-tips-adapter",
    "ncbatzmobilemoneyapi-tips-backgroundtasks",
    "ncbaugbillersapi-coreapi-backgroundtasks",
    "ncbaugbillersapi-elma-backgroundtasks",
    "ncbaugbillersapi-elmaadapter",
    "ncbaugbillersapi-nssf-adapter",
    "ncbaugbillersapi-nssf-backgroundtasks",
    "ncbaugbillersapi-nwsc-adapter",
    "ncbaugbillersapi-nwsc-backgroundtasks",
    "ncbaugbillersapi-trueafrican-adapter",
    "ncbaugbillersapi-trueafrican-backgroundtasks",
    "ncbaugbillersapi-umeme-backgroundtasks",
    "ncbaugbillersapi-ura-adapter",
    "ncbaugbillersapi-ura-backgroundtasks",
    "ncbaugbillersapi-zuku-adapter",
    "ncbaugbillersapi-zuku-backgroundtasks",
    "ncbaugmobilemoneyapi-airtel-adapter",
    "ncbaugmobilemoneyapi-airtel-backgroundtasks",
    "ncbaugmobilemoneyapi-airtelcallback",
    "ncbaugmobilemoneyapi-coreapi-api",
    "ncbaugmobilemoneyapi-coreapi-backgroundtasks",
    "ncbaugmobilemoneyapi-mtn-backgroundtasks",
    "ncbaugmobilemoneyapi-mtn-openapi-adapter",
    "ncbaugmobilemoneyapi-mtn-openapi-backgroundtasks",
    "ncbaugmobilemoneyapi-mtn-openapi-callback",
    "ncbaugmobilemoneyapi-mtnadapter",
    "payment",
    "spg-admin-portal",
    "spg-callbacks-api",
    "spg-checkout-core-api",
    "spg-checkout-merchant-api",
    "spg-core-chloride-exide-adapter",
    "spg-core-chloride-exide-background-tasks",
    "spg-core-jubilee-insurance-adapter",
    "spg-core-jubilee-insurance-background-tasks",
    "spg-merchant-portal",
    "spg-merchant-shared-adapter-api",
    "spg-merchant-shared-adapter-worker",
    "spg-muk-acmis-adapter",
    "spg-muk-acmis-background-tasks",
    "spg-roke-adapter",
    "spg-transactions-api",
    "spg-ura-adapter",
    "spg-ura-background-tasks",
    "spg-workers-checkout",
    "spg-workers-core",
    "t24coremiddleware-callback",
    "t24coremiddleware-core-mpesa-bulkpublisher",
    "t24coremiddleware-core-mtn-escrow",
    "t24coremiddleware-coreapi-backgroundtasks",
    "trade",
    "tradeposting",
]

SHIFT = 6               # spaces to strip from over-indented lines
BAD_ENTRY_INDENT = 14   # spaces before "- |" in bad entries
BAD_FIELD_INDENT = 16   # spaces before objectName/objectType/objectVersion in bad entries


def leading_spaces(line):
    return len(line) - len(line.lstrip(' '))


def fix_spc(spc_path):
    with open(spc_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    output = []
    in_objects = False

    for line in lines:
        stripped = line.lstrip().rstrip('\n\r')
        indent = leading_spaces(line)

        # Detect objects block start — matches "objects: |-" or "objects: |"
        if 'objects:' in line and not line.lstrip().startswith('#'):
            in_objects = True
            output.append(line)
            continue

        # Detect end of objects block — a key at indent <= 4 that isn't a comment
        if in_objects and indent <= 4 and stripped and not stripped.startswith('#'):
            in_objects = False

        if in_objects:
            # Over-indented "- |" — shift left
            if stripped == '- |' and indent >= BAD_ENTRY_INDENT:
                output.append(' ' * (indent - SHIFT) + '- |\n')
                continue

            # Over-indented object fields — shift left
            if indent >= BAD_FIELD_INDENT and stripped.startswith(
                ('objectName:', 'objectType:', 'objectVersion:')
            ):
                output.append(' ' * (indent - SHIFT) + stripped + '\n')
                continue

        output.append(line)

    with open(spc_path, 'w', encoding='utf-8') as f:
        f.writelines(output)


def count_bad(spc_path):
    with open(spc_path, 'r', encoding='utf-8') as f:
        return sum(
            1 for line in f
            if line.lstrip().rstrip('\n\r') == '- |'
            and leading_spaces(line) >= BAD_ENTRY_INDENT
        )


def main():
    script_dir = Path(__file__).parent.resolve()
    base_dir = script_dir / "apps" / "base"

    if not base_dir.exists():
        err(f"Base dir not found: {base_dir}")
        sys.exit(1)

    phase(f"Fixing SPC objects blocks for {len(SERVICES)} services")

    fixed = 0
    skipped = 0
    failed = 0
    total = len(SERVICES)

    for i, svc in enumerate(SERVICES, 1):
        spc_path = base_dir / svc / "secretproviderclass.yaml"
        print(f"\n  {BOLD}[{i}/{total}] {svc}{RST}")

        if not spc_path.exists():
            skip(f"{svc} — secretproviderclass.yaml not found")
            skipped += 1
            continue

        bad_before = count_bad(spc_path)

        if bad_before == 0:
            skip(f"{svc} — no over-indented entries found")
            skipped += 1
            continue

        info(f"Found {bad_before} over-indented entr{'y' if bad_before == 1 else 'ies'} to re-indent")

        # Backup before touching
        backup = Path(str(spc_path) + ".bak")
        shutil.copy2(spc_path, backup)

        try:
            fix_spc(spc_path)

            remaining = count_bad(spc_path)

            if remaining > 0:
                err(f"{svc} — {remaining} bad entr{'y' if remaining == 1 else 'ies'} still remain after fix")
                shutil.move(str(backup), str(spc_path))
                failed += 1
            else:
                backup.unlink(missing_ok=True)
                noun = 'entry' if bad_before == 1 else 'entries'
                ok(f"{svc} — re-indented {bad_before} {noun}")
                fixed += 1

        except Exception as e:
            err(f"{svc} — exception: {e}")
            if backup.exists():
                shutil.move(str(backup), str(spc_path))
            failed += 1

    phase("Summary")
    print(f"""
  {GRN}Fixed{RST}   : {fixed}
  {DIM}Skipped{RST} : {skipped}
  {RED}Failed{RST}  : {failed}
""")

    if failed > 0:
        err(f"{failed} service(s) failed — backups restored")
        sys.exit(1)

    print(f"  {GRN}{BOLD}All done.{RST}\n")
    print(f"  {DIM}Run detect-corruption.sh to verify all clear.{RST}\n")


if __name__ == "__main__":
    main()
