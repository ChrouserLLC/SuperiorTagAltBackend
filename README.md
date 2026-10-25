# Superior Tag Alt Backend

One Flask service that replaces three separate single-purpose backends, plus the
merged PlayFab CloudScript and the Unity client scripts that talk to them.

| Feature | What it does | Endpoint |
|---|---|---|
| **Player tracker** | Lobby join/leave, player join/leave, online counts -> Discord | `POST /api/tracker`, `POST /api/online-count` |
| **Custom reports** | In-game report -> moderation channel | `POST /api/report` |
| **Insta-ban** | A report can trigger a PlayFab ban via CloudScript | runs inside `/api/report` |
| **Redeem codes** | In-game REDEEM tab -> PlayFab catalog item | `POST /api/redeem`, `GET/POST /api/redeem-codes`, `GET /api/redeem-log` |
| **Dashboard** | Browser view of who is online, who is staff, and your codes | `GET /dashboard`, `GET /api/dashboard` |

Originally three separate Vercel projects (`Custom Reports`, `Custom Player
Tracker`, `Custom InstaBan`) each with their own `index.py`, `vercel.json` and
shared-secret variable. They are now one deployment.

---

## Layout

```
api/index.py              the whole backend (tracker + reports + instaban + dashboard)
api/dashboard.html        the dashboard UI, self-contained, no build step
cloudscript/SuperiorTagAlt.js   merged PlayFab CloudScript
Unity/ReportSender.cs     reports + insta-ban kick (Unity side)
Unity/PlayerTracker.cs    player tracker (Unity side)
seed_dev.py               local-only fake data, for looking at the dashboard
test_index.py             257 smoke tests, no credentials needed
.env.example              every env var, placeholders only
vercel.json               Vercel build config
```

---

## Dashboard

Open `https://<your-domain>/dashboard`. Paste `API_SECRET`, and it shows:

- players online, and how many are in the per-player list
- the online players with their role badge (Owner / Admin / Moderator / CC)
- the tracked-role counts
- whether PlayFab is configured, and where the count came from
- **redeem codes** — create, edit, enable/disable and delete them here
- **recent redemptions** — the last `REDEEM_LOG_MAX_ENTRIES` (default 25), newest first

It polls every 15s and stores the secret in `localStorage`.

### Managing codes from the dashboard

This is the place to put your codes; you do not need curl.

Cosmetic rewards still need a catalog tag first — open the item in
PlayFab (Catalogs (Legacy) → DLC → Items), add the tag `redeem:CODE`, then create
the same code below to set its label, max uses and enabled state. The panel tells
you this too, and flags any tagged item it cannot grant. Currency codes need no
catalog item and can be made entirely from the panel.

**Known limitation, stated plainly:** the online list lives in server memory, so
it resets whenever the host recycles the container (normal on Vercel). Entries
also expire after `ONLINE_PLAYER_TTL_SECONDS` (default 900s). The client only
posts tracker events on join and leave, so a long-running lobby can eventually
age out of the list even while people are still playing — the headline
"Players online" number comes from `/api/online-count`, which the client
refreshes on a 15s timer and is the authoritative figure. A permanent fix means
adding a heartbeat to `PlayerTracker`; that is a scope decision, not something
changed here.

---

## Setup

### 1. Deploy to Vercel

Import the repo at <https://github.com/ChrouserLLC/SuperiorTagAltBackend>. No
build settings needed — `vercel.json` points everything at `api/index.py`.

Then set the environment variables (Vercel > Settings > Environment Variables).
See `.env.example` for the full list with comments. The ones that matter:

| Variable | Required | Purpose |
|---|---|---|
| `API_SECRET` | **yes** | Shared secret the client sends as `secret` |
| `PLAYFAB_TITLE_ID` | for roles + bans | Role lookup and the insta-ban call |
| `PLAYFAB_SECRET_KEY` | for roles + bans | Same |
| `TRACKER_WEBHOOK_URL` | optional | Lobby/player events channel |
| `TRACKER_VIP_WEBHOOK_URL` | optional | Separate channel for tracked players |
| `REPORT_WEBHOOK_URL` | optional | Moderation channel for reports + bans |

Webhooks are optional. Leave them blank and the endpoints still return
`success: true` with `webhook_sent: false`.

Verify with `GET /api/health` — it reports which of these are configured.

### 2. Register the CloudScript

PlayFab Dashboard > your title > **Automation > CloudScript** > upload
`cloudscript/SuperiorTagAlt.js`.

Then edit two things in that file before going live:

```js
var INSTABAN_REPORTERS = ["YOUR_PLAYFAB_ID"];   // who may insta-ban
```

Also set a master admin in Title Data (key `MasterAdminId`, value = PlayFab ID).
That ID can grant/revoke tracker admins via `SetTrackerAdmin`.

### 3. Wire up Unity

Copy the two scripts into your project:

```
Unity/ReportSender.cs    ->  Assets/Scripts/Reports/ReportSender.cs
Unity/PlayerTracker.cs   ->  Assets/Scripts/PlayerTracker/PlayerTracker.cs
```

Both are already installed in `C:\Projects\SuperiorTag`.

`ReportSender` auto-creates itself via `EnsureCreated()`, so you only need to
set `ReportSecret` on the component if you place one in a scene. Leave
`BackendBaseUrl` blank and it inherits `SisterShipManager.BackendUrl` — one
config point for the whole integration.

`PlayerTracker` bootstraps itself via `RuntimeInitializeOnLoadMethod`; it needs
no scene object.

Set `ReportSecret` / `TrackerSecret` to the same value as `API_SECRET`.

The REDEEM tab lives in `GorillaComputer` (scene object), not a separate script.
Its `redeemSecret` field is optional — leave it empty and it falls back to
`ReportSender.ReportSecret`, so there is only one place to configure.

---

## Redeem codes

The in-game **REDEEM** tab POSTs to `/api/redeem`. The client never decides what
a code is worth; the table lives server-side in PlayFab TitleData under
`RedeemCodes`, so you can add or change codes without redeploying.

### Cosmetics: tag the catalog item

**Which cosmetic a code gives is decided by a tag on the item**, not by the
backend. Add `redeem:CODE` to the item's **Tags** field in the PlayFab
dashboard (Catalogs (Legacy) > DLC > Items). The backend scans the catalog for
those tags, so you never copy an Item ID anywhere.

```
Item ID  LBAAC.        Tags:  redeem:BETA
                      -> players type BETA, they get that item
```

Why tags and not Custom Data: the legacy DLC catalog does not expose Custom Data
through any API the backend can reach. `Server/GetCatalogItems` omits the field,
`Server/GetCatalogItem` 404s, and the catalog is not in TitleData. Tags are
returned, so they are the only marker that works.

Two things worth knowing:

- **The catalog stores ItemIds with a trailing dot** (`LBAAC.`) while the game
  uses them without (`LBAAC`). The backend resolves both spellings against the
  real catalog, so this never bites you.
- **A cosmetic code cannot be repointed from the table.** The catalog tag always
  wins. To change what a cosmetic code gives, move the tag.

### Currency: declare it in the table

Currency has no catalog item to tag, so those live in the settings table
(PlayFab TitleData `RedeemCodes`). This title's currencies are **SR** and **RM**.

```json
{
  "BETA": { "enabled": true, "max_uses": 0, "note": "announcement" },
  "GOLD": { "reward_type": "currency", "reward_id": "SR", "amount": 5000,
            "reward_label": "5000 SHINY ROCKS" }
}
```

| Field | Meaning |
|---|---|
| `reward_id` | A currency code (`SR` / `RM`) when `reward_type` is `currency`. |
| `amount` | How much currency to grant. |
| `reward_label` | What the player is shown in-game. |
| `max_uses` | Times **one player** may redeem it. `0` = once. |
| `enabled` | `false` retires the code without touching PlayFab. |
| `note` | Internal, never shown to players. |

An entry with a `reward_id` and an `amount` infers `currency`; with a
`reward_id` and no amount it infers `cosmetic` and is validated against the
catalog on save.

### Managing codes

```bash
# Set a label on a code that already has a catalog tag
curl -X POST https://<domain>/api/redeem-codes \
  -H 'Content-Type: application/json' \
  -d '{"secret":"<API_SECRET>","code":"BETA","reward_label":"Beta Tester"}'

# Create a currency code
curl -X POST https://<domain>/api/redeem-codes \
  -H 'Content-Type: application/json' \
  -d '{"secret":"<API_SECRET>","code":"GOLD","reward_type":"currency","reward_id":"SR","amount":5000}'

# List every code, with problems reported alongside
curl https://<domain>/api/redeem-codes -H 'X-Api-Secret: <API_SECRET>'

# Disable (leaves the catalog tag alone)
curl -X POST https://<domain>/api/redeem-codes \
  -H 'Content-Type: application/json' \
  -d '{"secret":"<API_SECRET>","code":"BETA","enabled":false}'

# Delete the settings entry (a catalog tag is removed in the PlayFab dashboard)
curl -X POST https://<domain>/api/redeem-codes \
  -H 'Content-Type: application/json' \
  -d '{"secret":"<API_SECRET>","code":"BETA","delete":true}'
```

Codes are case-insensitive; everything is stored upper-cased.

`GET /api/redeem-codes` also returns a `problems` array — for example if two
items claim the same code, or an item carries a bare `redeem:` tag with nothing
after it. Duplicates are not silently resolved: the first item wins and the clash
is reported.

### How "already used" is tracked

The player's redeemed codes are written to that player's **private UserData**
under `RedeemUsed`, not to TitleData. One shared TitleData value would grow
without bound and eventually hit PlayFab's value-size cap, silently losing
redemption history.

### Failure behaviour

If the grant fails — bad item id, unknown player, PlayFab down — the endpoint
returns **502** and the code is **not** marked as spent, so the player can retry.
Only a successful grant burns the code. The underlying PlayFab error is printed
to the server log as `[redeem] grant failed` and returned in the JSON `error`
field.

Cosmetic reward ids are validated against the real catalog when you save them,
so a typo fails immediately with a clear message instead of failing silently at
redemption time.

### Limits

The catalog is cached for 60s and the settings table for 30s, so changes take
that long to appear everywhere. If a catalog fetch fails, the previous catalog
is kept rather than blanking the code list.

PlayFab caps a TitleData value at 4000 bytes, so the settings table must stay
under that. The endpoint refuses to save a larger table rather than letting
PlayFab truncate it into unparseable JSON.

---

## Security caveat, stated plainly

> **Do not put secrets in `api/index.py`.** Commit `5f193bb` on this repo put
> the live PlayFab secret key, the API secret and all three Discord webhook
> URLs directly into the source as `os.environ.get(..., "real value")` defaults.
> The repo is private, so this was not a public leak, but those values are now
> in git history permanently, and every collaborator now has a PlayFab
> admin key. They should be set in Vercel environment variables only, and the
> PlayFab key should be rotated.

`API_SECRET` ships inside the APK. Anyone with `aapt` can extract it. This
is abuse reduction, not authentication — treat it as a speed bump.

Real authority lives in the CloudScript, not in Flask:

- `INSTABAN_REPORTERS` is checked **server-side** before any ban. The client
  cannot bypass it by editing the request.
- `SetTrackedPlayer` / `RemoveTrackedPlayer` require a tracker admin.
- `SetTrackerAdmin` requires the master admin.

The Flask `secret` check stops casual script-kiddies. The CloudScript
allowlists are what actually prevent a ban.

### Endpoints that expose player data

Discord needs an explicit User-Agent. Without one, urllib sends
`Python-urllib/3.12` and Discord's Cloudflare rejects it with **HTTP 403 error
1010**, so every embed fails silently while `/api/health` still reports the
webhook as configured. `DISCORD_USER_AGENT` overrides the default.

`/api/health` only checks that the webhook variables are **non-empty**. It does
not verify the URL is reachable or that Discord accepts it, so it is not proof
the embeds work. The real signal is `webhook_sent` in the `/api/tracker`
response, which `PlayerTracker` now prints to the Unity console.

These return PlayFab IDs and were open to anyone before this was fixed:

- `GET /api/online` returned the full player list unauthenticated. It now
  returns only the count unless `X-Api-Secret` is present.
- `GET /api/tracker/tracked` returned the whole CC/mod/admin/owner roster
  unauthenticated. It now requires the secret.

The secret is accepted in the `X-Api-Secret` header or a JSON `secret` field,
but **not** in a query string — query strings land in server logs and browser
history.

---

## Changes made during the merge

These were bugs in the originals, fixed here:

1. **`pf_request` crashed on an unconfigured PlayFab title.**
   `https://.playfabapi.com/...` — the empty title id raised `UnicodeError`
   from urllib's idna encoder, escaping as an HTTP 500 on *every* tracker
   event. Now returns `(False, {"errorMessage": ...})`.

2. **`urllib.request.Request(...)` was built outside the `try` block** in both
   `pf_request` and `post_webhook`. A malformed title id or a webhook pasted
   without `https://` raised `ValueError` straight out of the URL parser and
   took down the request with a 500. Both now build the request inside the
   `try`.

3. **`ReportSender` resolved `IJsonWrapper` to the wrong type.**
   This project contains a global-namespace dummy `IJsonWrapper : MonoBehaviour`
   left behind by AssetRipper (`Assets/Scripts/Assembly-CSharp/IJsonWrapper.cs`).
   The original cast to the unqualified name bound to that stub, not
   `LitJson.IJsonWrapper`, so insta-ban response parsing would not compile.
   Now fully qualified.

4. **`ReportSender`'s backend-URL fallback was dead code.**
   It reflected on a type `MetaAttestationv2` that does not exist in this
   project, so it always returned `""` and nothing was ever reported. Now
   reads `SisterShipManager.Instance.BackendUrl`.

---

## Discord bot

Slash commands answered by this backend (`api/discord_bot.py`), so nothing has
to run all day. Discord POSTs each command to `/api/discord/interactions`.

| Command | Who | What |
|---|---|---|
| `/players` | everyone | Current count, 1h and 24h peaks, and a chart of the last hour |
| `/status` | everyone | PlayFab, attestation, SisterShip, data freshness, KV |
| `/rooms` | everyone | Public rooms right now |
| `/player <name or id>` | staff | Role, ban, created, last login, last seen in a room |
| `/ban <player> <hours> <reason>` | staff | Ban through PlayFab; `0` hours = permanent |
| `/unban <player>` | staff | Lift every ban |
| `/code list / create / enable / disable / delete` | staff | Manage redeem codes |
| `/live start <channel>` / `/live stop` | staff | A message that keeps updating with the player count |

Reports get **Ban 24h / Ban 7d / Dismiss** buttons when `DISCORD_REPORT_CHANNEL_ID`
is set (they are then posted by the bot instead of the webhook).

The numbers come from the game: `PlayerCountReporter.cs` makes the Photon
master client of every room post the count once a minute. History needs KV
(Vercel > Storage > Upstash Redis); without it each serverless copy only sees
the reports it received.

### Setup (about 10 minutes)

1. https://discord.com/developers/applications > **New Application**.
2. **General Information**: copy the *Application ID* and *Public Key*.
3. **Bot**: *Reset Token* and copy it.
4. **Installation**: scopes `applications.commands` + `bot`, permissions
   *Send Messages*, *Embed Links*. Open the install link and add it to your server.
5. Vercel > this project > Environment Variables: `DISCORD_APP_ID`,
   `DISCORD_PUBLIC_KEY`, `DISCORD_BOT_TOKEN`, `DISCORD_STAFF_ROLE_IDS`, and
   optionally `DISCORD_REPORT_CHANNEL_ID`. Redeploy.
6. **General Information > Interactions Endpoint URL**:
   `https://superiortagaltbackend.vercel.app/api/discord/interactions` > Save.
   Discord tests it immediately; it only saves if the backend answers.
7. Register the commands (from this folder):
   ```powershell
   $env:DISCORD_APP_ID="..."; $env:DISCORD_BOT_TOKEN="..."; $env:DISCORD_GUILD_ID="your server id"
   python tools/register_discord_commands.py
   ```
8. Staff commands are hidden from everyone but admins at first. Server
   Settings > Integrations > your bot: allow your staff role. The backend also
   checks `DISCORD_STAFF_ROLE_IDS` itself, so hiding is only cosmetic.

Bans apply the next time the player logs in; someone already in a room stays
until they leave it.

## Tests

```
python test_index.py
python test_discord.py
```

`test_discord.py` signs interactions with a throwaway key exactly like Discord
and covers every command, the staff checks and the report buttons.

`test_index.py`: 134 checks covering auth, input validation, cooldowns, the PlayFab degradation
paths, map/game-mode/duration formatting, Discord embed shapes, the online
registry, the dashboard endpoints, the player-ID privacy regressions and the two
crash fixes above. Uses Flask's test client, so nothing leaves the machine and
no credentials are required.

All 134 pass.

**Not tested:** anything requiring real PlayFab credentials or a live Discord
webhook, and no run on a Quest device. The C# compiles clean against the
project's assemblies (exit 0), but that is a compile check, not a gameplay test.
