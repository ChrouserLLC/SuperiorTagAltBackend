# Redeem Codes — Setup Guide

How to make a cosmetic or currency redeemable, and how to debug it.

**The short version:** you never type an Item ID anywhere. Go to the PlayFab
catalog, open the item, add the tag `redeem:YOURCODE` to its **Tags** field, save.
Done — about 60 seconds later that code works in-game.

---

## 0. How it works

```
PlayFab catalog item  ──[tag: redeem:BETA]──>  backend scans catalog
                                                     │
player types BETA on the REDEEM tab  ──POST /api/redeem──>  grants that item
```

The backend keeps only *settings* (disabled? how many uses? your private note?).
It never stores what a cosmetic code gives — the catalog tag is the single source
of truth for that. That means you cannot accidentally hand out the wrong item by
fat-fingering an ID somewhere.

Currency is different: it has no catalog item to tag, so those codes are declared
in a small settings table.

---

## 1. Make a cosmetic redeemable

PlayFab Dashboard → **Superior Tag** (title `12304A`) → **Catalogs (Legacy)** →
**DLC** → **Items** → open the item you want to give.

In the **Tags** box, add:

```
redeem:BETA
```

Press **Save item**. That's it.

Within about 60 seconds the code is live. No Unity rebuild, no redeploy, no
backend change.

![tags field](https://playfab.com) *(the Tags box sits under Item image URI)*

### Rules for the tag

| Rule | Why |
|---|---|
| Must start with `redeem:` | Anything else is ignored |
| Case doesn't matter | `redeem:beta` and `redeem:BETA` are the same code |
| No spaces after the colon | `redeem: BETA` would make the code `" BETA"` — trim it |
| One code per tag | An item can hold several tags, e.g. `redeem:BETA` and `redeem:VIP` |
| Only one item per code | Two items claiming `redeem:BETA` is reported as a problem, first one wins |

---

## 2. Check it worked

```powershell
$S = "YOUR_API_SECRET"
$U = "https://superiortagaltbackend.vercel.app"

curl.exe -s "$U/api/redeem-codes" -H "X-Api-Secret: $S"
```

You should see your code in `codes`, e.g.:

```json
{"success": true, "tag_prefix": "redeem:", "problems": [], "codes": {
  "BETA": {"reward_type": "cosmetic", "reward_id": "LBAAC.",
           "reward_label": "LBAAC.", "max_uses": 0, "enabled": true,
           "amount": 0, "note": "", "source": "catalog_tag"}
}}
```

**Check the `problems` array.** It's empty when everything's fine. It tells you
about duplicate codes, bare `redeem:` tags, and typos, instead of failing
silently.

`reward_label` falls back to the Item ID because every legacy DLC item has an
empty Display Name. Set a nicer label with step 3.

---

## 3. Give it a proper name and behaviour

Optional, but worth it — the player sees the label.

⚠️ **Windows note:** `curl -d "{...}"` **silently loses the double quotes** in
PowerShell and you get `bad secret`. Always send the body from a file with
`--data-binary "@file"`.

```powershell
$body = @{
  secret       = $S
  code         = "BETA"
  reward_label = "BETA TESTER"
  note         = "Discord announcement 2026-10"
} | ConvertTo-Json -Compress

$f = "$env:TEMP\redeem.json"
[System.IO.File]::WriteAllText($f, $body)

curl.exe -s -X POST "$U/api/redeem-codes" `
  -H "Content-Type: application/json" `
  --data-binary "@$f"
```

| What you send | Effect |
|---|---|
| `reward_label` | Friendly name shown in-game instead of the Item ID |
| `note` | Private reminder to you. Never shown to players. |
| `enabled: false` | Retires the code **without touching PlayFab** — flip it back any time |
| `max_uses: 5` | That player may claim it 5 times. `0` (default) = once |
| `delete: true` | Removes the settings entry. The catalog tag is untouched |

Only the fields you send change; everything else is preserved.

---

## 4. Make a currency code

Currency codes go in the settings table, because there's no item to tag. This
title uses **SR** (746 catalog items priced against it) and **RM** (19).

```powershell
$body = @{
  secret       = $S
  code         = "GOLD"
  reward_type  = "currency"
  reward_id    = "SR"
  amount       = 5000
  reward_label = "5000 SHINY ROCKS"
} | ConvertTo-Json -Compress

[System.IO.File]::WriteAllText($f, $body)
curl.exe -s -X POST "$U/api/redeem-codes" -H "Content-Type: application/json" --data-binary "@$f"
```

Currency rules:

- `reward_id` is the **currency code** (`SR` or `RM`), not an Item ID.
- `amount` is **required**. A currency code with no amount is rejected.
- Sending `reward_id` + `amount` without `reward_type` infers `currency`.
- Sending `reward_id` with **no** amount infers `cosmetic`, and is then checked
  against the catalog — so a typo'd currency code gets a clear error instead of
  failing silently later.

---

## 5. Test in-game

1. Open Unity, let it compile, press Play.
2. Wait for PlayFab sign-in (look for `Version Superior187` in the log).
3. At the computer, arrow down to **REDEEM**.
4. Type the code on the on-screen keyboard — `BETA`.
5. Press **ENTER**.

Should look like:

```
REDEEM A CODE

TYPE YOUR CODE AND PRESS ENTER.
USE DELETE TO ERASE A CHARACTER.
USE UP AND DOWN TO LEAVE THIS TAB.

CODE: -

CODE ACCEPTED.

YOU RECEIVED
  COSMETIC
  BETA TESTER
  (LBAAC.)
```

The cosmetic refreshes immediately — no restart needed. Console shows
`[Redeem] granted: ...`.

---

## 6. Verify the item actually landed

The grant goes through PlayFab, which needs a **real account**. Redeeming with a
made-up ID always fails with `HTTP 404` — expected, not a bug.

**PlayFab Dashboard** → title → **Players** → search your display name →
**Explorer** → `Inventory`. The item should be there. Or just wear it.

### Re-using your own code

Each code is one reward per player, so testing with your own account burns it.
Make a second code to keep testing, or set `max_uses`.

---

## Player-facing messages

Every message the REDEEM tab can show, and what it means.

| On screen | Cause | Fix |
|---|---|---|
| `TYPE A CODE FIRST.` | ENTER on an empty code | — |
| `REDEEM IS NOT CONFIGURED ON THIS BUILD.` | `redeemBackendUrl` blank on the GorillaComputer component | Set it in the Inspector |
| `CODE NOT RECOGNISED.` | No tag, no settings entry | Check the tag exists and is spelled `redeem:CODE`; list with `/api/redeem-codes` |
| `THAT CODE IS NO LONGER ACTIVE.` | Tag exists, `enabled: false` | Send `enabled: true` |
| `YOU HAVE ALREADY USED THAT CODE.` | This player claimed it (or hit `max_uses`) | New code, or raise `max_uses` |
| `SIGN IN BEFORE REDEEMING A CODE.` | Client had no PlayFab ID | Wait for sign-in, retry |
| `WAIT N SECONDS AND TRY AGAIN.` | 5s rate limit per player+code | Wait |
| `COULD NOT REACH THE SERVER. TRY AGAIN.` | Network / not deployed | Console has the HTTP error |
| `COULD NOT GRANT THE REWARD. TRY AGAIN LATER.` | PlayFab rejected the grant | See below |
| `UNREADABLE SERVER RESPONSE.` | Unexpected reply | Console: `[Redeem] response parse failed` |
| `CODE ACCEPTED.` + `YOU RECEIVED` | Worked | — |

### `COULD NOT GRANT THE REWARD` — usual causes

Reason is in the Console as `[Redeem] send failed`, in the JSON `error` field,
and in Vercel logs as `[redeem] grant failed`.

| Server says | Meaning |
|---|---|
| `HTTP 404` / `Entity not found` | Player doesn't exist, or the item ID is wrong |
| `Invalid params` | Item ID not in the catalog |
| `HTTP 5xx` | PlayFab down — **code not burned, just retry** |

**A failed grant never burns the code.** Deliberate — you don't want people
losing a code to a blip.

---

## Gotchas

**The catalog stores ItemIds with a trailing dot** (`LBAAC.`) while the game uses
them without (`LBAAC`). You can see this on the dashboard. The backend resolves
both spellings against the real catalog, so it never bites you — but it's why you
shouldn't hand-type Item IDs at all.

**Catalog changes take ~60s**, settings take ~30s. Both are cached so a redeem
doesn't hammer PlayFab.

**A catalog fetch failure keeps the old catalog** rather than blanking every
code. A brief PlayFab outage won't take your codes away.

**Settings live in TitleData `RedeemCodes`, capped at 4000 bytes.** The API
refuses to save a larger table rather than letting PlayFab truncate it into
unparseable JSON. Retire old settings entries if you ever approach it. Cosmetic
codes don't use this space at all — they're just tags — so it fills slowly.

**The secret ships inside the game.** It stops casual abuse; it isn't real
authentication. Fine for handing out cosmetics. Don't put anything genuinely
valuable behind it.

---

## Redeploying after changing `api/index.py`

```powershell
cd C:\Projects\SuperiorTagAltBackend
python test_index.py          # 235 tests, no credentials needed
git add api/index.py
git commit -m "what changed"
git push origin main          # Vercel deploys from GitHub automatically
```

**Editing codes and tags needs no deploy.** That's the point of keeping them in
PlayFab.