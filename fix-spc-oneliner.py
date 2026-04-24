#!/usr/bin/env python3
# =============================================================================
# fix-spc-oneliner.py
# Fixes SPC files where the objects block is a single escaped string
# with literal \n characters. Converts to proper multiline block with
# correct indentation. Removes over-indented duplicate entries.
#
# Usage: python3 fix-spc-oneliner.py
# =============================================================================

import sys
import re
import shutil
from pathlib import Path

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

SERVICES = [
    "ncbaugbillersadminportal",
    "ncbaugbillersapi-coreapi-api",
    "ncbaugbillersapi-umeme-adapter",
    "newnlscoreservices",
    "nlsintellectsync",
    "nlsintellectsync-rw",
    "nlsintellectsync-ug",
    "nlstzsync",
]

def leading_spaces(line):
    return len(line) - len(line.lstrip(' '))

def is_oneliner(spc_path):
    with open(spc_path, 'r', encoding='utf-8') as f:
        for line in f:
            if re.match(r'\s+objects:\s+"array:\\n', line) or \
               re.match(r"\s+objects:\s+'array:\\n", line):
                return True
    return False

def fix_oneliner(spc_path):
    with open(spc_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # Find the objects line index and its indentation
    objects_line_idx = None
    objects_key_indent = None  # how many spaces before "objects:"

    for idx, line in enumerate(lines):
        if re.match(r'\s+objects:\s+"array:\\n', line) or \
           re.match(r"\s+objects:\s+'array:\\n", line):
            objects_line_idx = idx
            objects_key_indent = leading_spaces(line)
            break

    if objects_line_idx is None:
        return False, "Could not find one-liner objects line"

    # Extract the escaped string value
    line = lines[objects_line_idx]
    # Match quoted value (double or single quotes)
    m = re.search(r'objects:\s+"(.*)"', line) or re.search(r"objects:\s+'(.*)'", line)
    if not m:
        return False, "Could not extract escaped string value"

    escaped = m.group(1)

    # Unescape
    raw = escaped.replace('\\n', '\n').replace('\\"', '"').replace("\\'", "'")

    # Split into lines
    raw_lines = raw.split('\n')

    # Detect standard entry indent from first "- |" in the raw content
    std_entry_indent = None
    for rl in raw_lines:
        if rl.lstrip().rstrip() == '- |':
            std_entry_indent = leading_spaces(rl)
            break

    if std_entry_indent is None:
        return False, "Could not detect standard entry indent in escaped string"

    info(f"Raw string entry indent: {std_entry_indent} spaces")
    info(f"objects: key indent: {objects_key_indent} spaces")

    # The target indent for entries in the output file:
    # objects: is at objects_key_indent spaces
    # array: should be at objects_key_indent + 2
    # - | should be at objects_key_indent + 4
    # objectName: should be at objects_key_indent + 6
    target_array_indent  = objects_key_indent + 2
    target_entry_indent  = objects_key_indent + 4
    target_field_indent  = objects_key_indent + 6

    # Remove over-indented duplicate entries from raw lines
    # Any "- |" with indent > std_entry_indent is a duplicate
    clean_raw = []
    skip_block = False
    for rl in raw_lines:
        stripped = rl.lstrip().rstrip()
        indent = leading_spaces(rl)

        if stripped == '- |':
            if indent > std_entry_indent:
                skip_block = True
                continue
            else:
                skip_block = False

        if skip_block:
            if stripped.startswith(('objectName:', 'objectType:', 'objectVersion:')):
                continue
            else:
                skip_block = False

        clean_raw.append(rl)

    removed = sum(1 for rl in raw_lines if rl.lstrip().rstrip() == '- |') - \
              sum(1 for rl in clean_raw if rl.lstrip().rstrip() == '- |')
    if removed > 0:
        info(f"Removed {removed} duplicate entr{'y' if removed == 1 else 'ies'} from string")

    # Now re-indent raw lines to correct file indentation
    # raw lines use std_entry_indent for "- |"
    # we need to map that to target_entry_indent
    indent_delta = target_entry_indent - std_entry_indent

    new_object_lines = []
    # First line is always "array:"
    new_object_lines.append(' ' * target_array_indent + 'array:\n')

    for rl in clean_raw:
        stripped = rl.lstrip().rstrip()
        if not stripped or stripped == 'array:':
            continue  # skip empty lines and the array: line (we added it above)

        raw_indent = leading_spaces(rl)
        new_indent = raw_indent + indent_delta

        # Clamp minimum to target_entry_indent
        new_indent = max(new_indent, target_entry_indent)

        new_object_lines.append(' ' * new_indent + stripped + '\n')

    # Build the replacement block
    # objects: |-   (at objects_key_indent)
    # then the array lines
    replacement_lines = []
    replacement_lines.append(' ' * objects_key_indent + 'objects: |-\n')
    replacement_lines.extend(new_object_lines)

    # Replace the original objects line with the new multiline block
    new_file_lines = (
        lines[:objects_line_idx] +
        replacement_lines +
        lines[objects_line_idx + 1:]
    )

    with open(spc_path, 'w', encoding='utf-8') as f:
        f.writelines(new_file_lines)

    kept = sum(1 for rl in clean_raw if rl.lstrip().rstrip() == '- |')
    return True, f"Converted to multiline block ({kept} entries, {removed} duplicates removed)"


def main():
    script_dir = Path(__file__).parent.resolve()
    base_dir = script_dir / "apps" / "base"

    if not base_dir.exists():
        err(f"Base dir not found: {base_dir}")
        sys.exit(1)

    phase(f"Fixing one-liner SPC objects blocks for {len(SERVICES)} services")

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

        if not is_oneliner(spc_path):
            skip(f"{svc} — not a one-liner")
            skipped += 1
            continue

        backup = Path(str(spc_path) + ".bak")
        shutil.copy2(spc_path, backup)

        try:
            success, message = fix_oneliner(spc_path)

            if not success:
                err(f"{svc} — {message}")
                shutil.move(str(backup), str(spc_path))
                failed += 1
                continue

            if is_oneliner(spc_path):
                err(f"{svc} — still a one-liner after fix")
                shutil.move(str(backup), str(spc_path))
                failed += 1
            else:
                backup.unlink(missing_ok=True)
                ok(f"{svc} — {message}")
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
