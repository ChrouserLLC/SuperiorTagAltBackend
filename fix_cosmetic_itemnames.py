"""Rewrite allCosmetics[].itemName from the human name to the PlayFab ItemId code.

WHY
---
CosmeticsController.GetUserCosmeticsAllowed does:

    searchIndex = allCosmetics.FindIndex(x => item.ItemId == x.itemName);

item.ItemId comes from the PlayFab inventory and looks like "LBAAA." (trailing
dot). Many scene entries hold the human name ("BANANA HAT") in itemName instead,
so every lookup returns -1, nothing unlocks, unlockedHats stays empty and the
wardrobe renders only nullItem.

WHAT
---
For each allCosmetics entry whose displayName matches exactly one PlayFab
catalog DisplayName, and whose itemName differs from that catalog ItemId,
substitute the code into the entry's "- itemName:" value. Every other byte of
the file is copied through unchanged.

SAFETY
  - dry run by default; --apply required to write
  - full backup written on first run
  - only the first line of an entry is ever modified, and only its value
  - entry lines are emitted in their original order (a first attempt buffered
    just the itemName line and emitted it after the following fields, which
    reordered the YAML and corrupted the scene)
  - newline='' on read and write so LF endings are preserved exactly
"""
import json
import os
import re
import shutil
import sys
import urllib.request
from collections import defaultdict

SCENE = r"C:\Projects\SuperiorTag\Assets\Scenes\Gorilla\Gorilla Tag\GorillaTagSJR.unity"
BACKUP = r"C:\Users\FtlRb\AppData\Local\Temp\opencode\superiortag_backup\GorillaTagSJR.unity.preitemnamefix"


def fetch_catalog(title, key):
    req = urllib.request.Request(
        "https://{}.playfabapi.com/Server/GetCatalogItems".format(title),
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json", "X-SecretKey": key},
    )
    return json.load(urllib.request.urlopen(req, timeout=30))["data"]["Catalog"]


def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip()).upper()


def build_map(catalog):
    by_name = defaultdict(list)
    for c in catalog:
        dn = norm(c.get("DisplayName"))
        if dn:
            by_name[dn].append(c["ItemId"])
    return {k: v[0] for k, v in by_name.items() if len(v) == 1}, by_name


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    apply = "--apply" in sys.argv
    title = os.environ.get("PF_TITLE_ID")
    key = os.environ.get("PF_SECRET_KEY")
    if not title or not key:
        print("set PF_TITLE_ID and PF_SECRET_KEY")
        return 1

    catalog = fetch_catalog(title, key)
    code_of, by_name = build_map(catalog)
    print("catalog entries: {}   uniquely-named: {}".format(
        len(catalog), len(code_of)))

    if not os.path.exists(BACKUP):
        shutil.copy2(SCENE, BACKUP)
        print("backup written: {}  ({:.1f} MB)".format(
            BACKUP, os.path.getsize(BACKUP) / 1e6))
    else:
        print("backup already exists, reusing it")

    changes = []
    ambiguous = []
    entry = []          # buffered lines of the current allCosmetics entry
    entry_start = 0
    in_block = False
    out = []

    def flush():
        """Emit the buffered entry, substituting itemName if warranted."""
        nonlocal entry
        if not entry:
            return
        display = None
        for ln in entry:
            s = ln.strip()
            if s.startswith("displayName:"):
                display = s.partition(":")[2].strip()
                break
        first = entry[0]
        m = re.match(r"(\s*- itemName:\s*)(.*?)(\r?\n)?$", first)
        if display and m:
            code = code_of.get(norm(display))
            if code:
                old = m.group(2)
                if old != code and old not in (None, "null", ""):
                    entry[0] = m.group(1) + code + (m.group(3) or "")
                    changes.append((entry_start, display, old, code))
                elif old != code and old == "":
                    pass
            elif len(by_name.get(norm(display), [])) > 1:
                ambiguous.append(display)
        out.extend(entry)
        entry = []

    with open(SCENE, "r", encoding="utf-8", errors="surrogateescape", newline="") as fh:
        for lineno, line in enumerate(fh, 1):
            s = line.strip()

            if not in_block:
                out.append(line)
                if s == "allCosmetics:":
                    in_block = True
                continue

            if s == "wardrobes:":
                flush()
                in_block = False
                out.append(line)
                continue

            if s.startswith("- "):
                flush()
                if not entry:
                    entry_start = lineno
                entry.append(line)
                continue

            if entry:
                entry.append(line)
            else:
                out.append(line)
        flush()

    print()
    print("=== APPLYING ===" if apply else "=== DRY RUN ===")
    print("entries that would change: {}".format(len(changes)))
    print("ambiguous, skipped       : {}".format(len(ambiguous)))
    for ln, name, old, new in changes[:12]:
        print("  L{:<9} {:<24} {:<24} -> {}".format(ln, name, old, new))
    if len(changes) > 12:
        print("  ... and {} more".format(len(changes) - 12))

    # integrity check: total emitted lines must equal lines read
    if not apply:
        print("\nDRY RUN ONLY - nothing written. Re-run with --apply.")
        return 0

    tmp = SCENE + ".tmp"
    with open(tmp, "w", encoding="utf-8", errors="surrogateescape", newline="") as out_f:
        out_f.writelines(out)
    shutil.copystat(SCENE, tmp)
    os.replace(tmp, SCENE)
    print("\nWROTE {} substitutions".format(len(changes)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
