# Redeem Codes — Setup Guide

How to create codes, what players see, and how to debug it.

The whole point: **the code table lives on the backend, not in the game.** You can
add or change codes any time and they take effect within ~30 seconds. No Unity
rebuild, no redeploy.

---

## 0. What you already have

| Piece | Where |
|---|---|
| In-game tab | `GorillaComputer.cs` → `ComputerState.Redeem` (`REDEEM` in the function menu) |
| Backend endpoint | `api/index.py` → `POST /api/redeem` |
| Code management | `api/index.py` → `GET/POST /api/redeem-codes` |
| Storage | PlayFab **TitleData** key `RedeemCodes` |
| Redemption history | PlayFab **UserData** key `RedeemUsed` (private, per player) |

Deployed and live at `https://superiortagaltbackend.vercel.app`.

The secret is the same `API_SECRET` the report and tracker endpoints use. On the
Unity side, `GorillaComputer.redeemSecret` is empty by default and falls back to
`ReportSender.ReportSecret` — so there is nothing new for you to configure.

---

## 1. Find the cosmetic Item ID you want to give

`reward_id` is a **PlayFab catalog `ItemId`** — the same short code the game uses
for cosmetics, like `LBAAA`, `LFAAB`, `LBAAB`, `LFAAF`.

Two ways to find them:

**PlayFab Dashboard** → your title (12304A) → **Catalog** → open the item →
the **Item Id** field is what you want.

**Or** just look in-game. The cosmetic list your client already downloads is
printed in the Player log when you join a room:

```
successful result. allowed cosmetics are:
Slingshot.LBATS.Early Access Supporter Pack.LBAAA.LBAAB.LBAAC...
```

Everything in that list is a valid `reward_id`.

---

## 2. Create a code

> **Windows note:** `curl -d "{...}"` **silently loses the double quotes** in
> PowerShell and the server replies `bad secret`. Always send the body from a
> file with `--data-binary "@file"`. The commands below already do that.

```powershell
$S = "YOUR_API_SECRET"
$U = "https://superiortagaltbackend.vercel.app"

$body = @{
  secret      = $S
  code        = "BETA"
  reward_id   = "LBAAA"
  reward_label = "BETA TESTER"
  note        = "Discord beta announcement - 2026-10"
} | ConvertTo-Json -Compress

$f = "$env:TEMP\redeem.json"
[System.IO.File]::WriteAllText($f, $body)

curl.exe -s -X POST "$U/api/redeem-codes" `
  -H "Content-Type: application/json" `
  --data-binary "@$f"
```

Expected reply:

```json
{"success": true, "code": "BETA", "codes": {
  "BETA": {"reward_type": "cosmetic", "reward_id": "LBAAA",
           "reward_label": "BETA TESTER", "credits": 0,
           "max_uses": 0, "enabled": true, "note": "..."}}}
```

The code is live within about 30 seconds.

### Short form

If the label is just the item id you don't need the extras:

```json
{"secret": "...", "code": "BETA", "reward_id": "LBAAA"}
```

---

## 3. Check what you've got

```powershell
curl.exe -s "$U/api/redeem-codes" -H "X-Api-Secret: $S"
```

Note: listing uses the `X-Api-Secret` **header**, not a body, so the secret never
lands in a shell history or a server access log.

---

## 4. Test it in-game

1. Open Unity, let it compile, press Play.
2. Wait for PlayFab sign-in to finish (look for `Version Superior187` in the log).
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
  (LBAAA)
```

The cosmetic refreshes immediately — no restart needed.

Console output to watch for:

```
[Redeem] granted: CODE ACCEPTED.
...
```

---

## 5. Verify a real account actually got the item

The grant goes through PlayFab's `GrantCatalogItem`, which needs a **real
PlayFab account**. Redeeming with a made-up ID always fails with HTTP 404 —
that's expected, not a bug.

To confirm properly:

**PlayFab Dashboard** → your title → **Players** → search your display name →
**Explorer** → `Inventory` → the item should be there.

Or just wear it in-game.

### Re-using your own code for testing

Because every code is single-use per player, you'll burn `BETA` on your own
account the first time. Create a fresh one to test again, or raise `max_uses`.

---

## Field reference

| Field | Required | What it does |
|---|---|---|
| `code` | yes | The code players type. Case-insensitive — `beta` and `BETA` are the same code. Stored upper-cased. |
| `reward_id` | yes* | PlayFab catalog `ItemId` that gets granted. The field that actually matters. |
| `reward_label` | no | Shown to the player. Defaults to `reward_id`. |
| `reward_type` | no | `cosmetic` or `credits`. Defaults to `cosmetic`. |
| `credits` | no | Display only. GorillaNetworking has no separate currency, so `credits` is also just a catalog item id. |
| `max_uses` | no | How many times **one player** may redeem it. `0` = once. |
| `enabled` | no | `false` retires a code without deleting it. |
| `note` | no | For you. Never shown to a player. |
| `delete` | no | `true` removes the code entirely. |

\* unless you set `credits` to a positive number.

---

## Managing codes

### Edit an existing code

Only the fields you send change — everything else is preserved.

```powershell
$body = @{ secret=$S; code="BETA"; reward_label="BETA TESTER v2" } | ConvertTo-Json -Compress
# ... same --data-binary "@$f" pattern
```

### Retire a code without deleting it

```json
{"secret": "...", "code": "BETA", "enabled": false}
```

Players get `THAT CODE IS NO LONGER ACTIVE.` The history stays intact, so you can
flip it back on later.

### Delete

```json
{"secret": "...", "code": "BETA", "delete": true}
```

### Let a player claim more than once

```json
{"secret": "...", "code": "DAILY", "reward_id": "LFAAF", "max_uses": 7}
```

---

## Player-facing messages

Every message the REDEEM tab can show, and what it actually means.

| On screen | Cause | Fix |
|---|---|---|
| `TYPE A CODE FIRST.` | Pressed ENTER on an empty code | — |
| `REDEEM IS NOT CONFIGURED ON THIS BUILD.` | `redeemBackendUrl` is blank on the GorillaComputer component | Set it in the Inspector |
| `CODE NOT RECOGNISED.` | No such code in the table | Check spelling; list with `/api/redeem-codes` |
| `THAT CODE IS NO LONGER ACTIVE.` | Code exists but `enabled: false` | Set `enabled: true` |
| `YOU HAVE ALREADY USED THAT CODE.` | This player already claimed it (or hit `max_uses`) | Make a new code, or raise `max_uses` |
| `SIGN IN BEFORE REDEEMING A CODE.` | Client had no PlayFab ID | Wait for PlayFab sign-in, then retry |
| `WAIT N SECONDS AND TRY AGAIN.` | Rate limit (5s per player+code) | Just wait |
| `COULD NOT REACH THE SERVER. TRY AGAIN.` | Network, or backend not deployed | Check Console for the HTTP error |
| `COULD NOT GRANT THE REWARD. TRY AGAIN LATER.` | PlayFab rejected the grant | See below |
| `UNREADABLE SERVER RESPONSE.` | Server replied with something unexpected | Check Console for `[Redeem] response parse failed` |
| `CODE ACCEPTED.` + `YOU RECEIVED` | Worked | — |

### `COULD NOT GRANT THE REWARD` — the four usual causes

The underlying reason is in the Console log as `[Redeem] send failed` / in the
JSON's `error` field, and in the Vercel logs as `[redeem] grant failed`.

| Cause | Server says | Meaning |
|---|---|---|
| Wrong `reward_id` | `Invalid params` / `Item not found` | Item id isn't in the PlayFab catalog |
| Bad PlayFab ID | `HTTP 404` / `Entity not found` | Player doesn't exist, or the ID is malformed |
| Item not in catalog | `Entity not found` | Item id typo |
| PlayFab down | `HTTP 5xx` | Temporary — **the code is not burned, just retry** |

**A failed grant never burns the code.** The player can retry once PlayFab is
healthy. That's deliberate — you don't want people to lose a code to a blip.

---

## Limits and gotchas

**TitleData is capped at 4000 bytes** for the entire code table. Roughly 40–60
codes depending on how much metadata each has. If you exceed it the API refuses
to save and returns a clear error rather than letting PlayFab truncate the table
into unparseable JSON. If you ever hit this, retire old codes.

**30-second cache.** After you create or edit a code it takes up to 30 seconds
to become visible. The cache only kicks in once the table is non-empty, so a
transient PlayFab outage can't leave players stuck on "no codes".

**Redemption history is per-player, in UserData.** Not TitleData. A shared
TitleData value would grow forever and eventually hit the size cap, silently
losing history.

**The secret ships inside the game.** It's in the client binary and can be
extracted. It stops casual abuse — someone can't casually mint cosmetics. It is
not real authentication. The real authority for bans and staff actions lives in
the PlayFab CloudScript allowlists, and this should too.

---

## Redeploying after changing `api/index.py`

The backend deploys from GitHub on push to `main`. So:

```powershell
cd C:\Projects\SuperiorTagAltBackend
git add api/index.py
git commit -m "what changed"
git push origin main
```

Vercel picks it up automatically. Watch it at
`https://vercel.com/ChrouserLLC` (or wherever the project lives) → Deployments.

**Editing codes does NOT need a deploy** — that's the whole point of keeping
them in TitleData.

Run the tests before pushing:

```powershell
python test_index.py
```

186 tests, no credentials needed, nothing leaves the machine.