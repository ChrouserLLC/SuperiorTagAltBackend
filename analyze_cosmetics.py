"""Read-only match analysis: scene allCosmetics vs PlayFab catalog.

Does NOT modify anything. Reports how many scene cosmetics can be matched to a
PlayFab catalog code, which decides whether rewriting allCosmetics[].itemName
with the real ItemId is safe.
"""
import json
import re
import sys
import urllib.request
from collections import defaultdict

TITLE = "12304A"
KEY = "9U76KWPK7KPWTJNBDJ5AW4MDYGZ688C4XRQZBFYI33O7NZ7HTN"
SCENE = r"C:\Projects\SuperiorTag\Assets\Scenes\Gorilla\Gorilla Tag\GorillaTagSJR.unity"


def fetch_catalog():
    req = urllib.request.Request(
        "https://{}.playfabapi.com/Server/GetCatalogItems".format(TITLE),
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json", "X-SecretKey": KEY},
    )
    return json.load(urllib.request.urlopen(req, timeout=30))["data"]["Catalog"]


def parse_all_cosmetics(path):
    """Stream the scene and pull the allCosmetics array out of the YAML."""
    entries = []
    in_block = False
    cur = None
    start = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            if not in_block:
                # indentation varies with nesting depth, so match on the key only
                if line.strip() == "allCosmetics:":
                    in_block = True
                    start = lineno
                continue
            stripped = line.strip()
            if stripped == "wardrobes:":
                break
            if stripped.startswith("- "):
                if cur:
                    entries.append(cur)
                cur = {}
                stripped = stripped[2:]
            elif not stripped:
                continue
            if ":" in stripped and cur is not None:
                k, _, v = stripped.partition(":")
                cur[k.strip()] = v.strip()
            if cur is not None and "isNullItem" in cur:
                entries.append(cur)
                cur = None
    if cur:
        entries.append(cur)
    return entries, start


def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip()).upper()


def main():
    catalog = fetch_catalog()
    by_name = defaultdict(list)
    for c in catalog:
        dn = norm(c.get("DisplayName"))
        if dn:
            by_name[dn].append(c["ItemId"])

    entries, start = parse_all_cosmetics(SCENE)
    print("scene allCosmetics starts at line {}".format(start))
    print("entries parsed: {}".format(len(entries)))
    print()

    matched, unmatched, ambiguous = [], [], []
    for e in entries:
        name = e.get("displayName", "")
        item = e.get("itemName", "")
        key = norm(name) or norm(item)
        hits = by_name.get(key, [])
        if len(hits) == 1:
            matched.append((item, name, hits[0]))
        elif len(hits) > 1:
            ambiguous.append((item, name, hits))
        else:
            unmatched.append((item, name))

    print("=== MATCH RESULT ===")
    print("  matched exactly (1 code) : {}".format(len(matched)))
    print("  ambiguous (>1 code)       : {}".format(len(ambiguous)))
    print("  unmatched (no code)       : {}".format(len(unmatched)))
    print()

    real = [m for m in matched if m[2] != m[0]]
    already = [m for m in matched if m[2] == m[0]]
    print("  of the matched, how many already carry the code in itemName?")
    print("    already correct : {}".format(len(already)))
    print("    need rewriting  : {}".format(len(real)))
    print()

    if already[:10]:
        print("--- sample already-correct ---")
        for i, n, c in already[:10]:
            print("  {:<24} itemName={}".format(n, i))

    if real[:15]:
        print("--- sample needing rewrite ---")
        for i, n, c in real[:15]:
            print("  {:<24} itemName={:<24} -> {}".format(n, i or "<null>", c))

    if unmatched[:25]:
        print("--- sample UNMATCHED (no catalog DisplayName) ---")
        for i, n in unmatched[:25]:
            print("  displayName={:<26} itemName={}".format(n or "<empty>", i or "<null>"))

    if ambiguous[:10]:
        print("--- sample AMBIGUOUS ---")
        for i, n, hits in ambiguous[:10]:
            print("  displayName={:<26} -> {}".format(n, hits[:6]))

    # how many distinct categories / null item
    print()
    print("=== sanity ===")
    print("  entries with isNullItem truthy: {}".format(
        sum(1 for e in entries if e.get("isNullItem") not in ("0", "false", ""))))
    print("  entries with empty displayName: {}".format(
        sum(1 for e in entries if not e.get("displayName"))))
    print("  distinct displayName values   : {}".format(
        len({e.get('displayName','') for e in entries})))
    print("  catalog names not used by scene: {}".format(
        len({n for n in by_name} - {norm(e.get('displayName','')) for e in entries})))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
