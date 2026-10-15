# Superior Tag Alt Backend

One Flask service that replaces three separate single-purpose backends, plus the
merged PlayFab CloudScript and the Unity client scripts that talk to them.

| Feature | What it does | Endpoint |
|---|---|---|
| **Player tracker** | Lobby join/leave, player join/leave, online counts -> Discord | `POST /api/tracker`, `POST /api/online-count` |
| **Custom reports** | In-game report -> moderation channel | `POST /api/report` |
| **Insta-ban** | A report can trigger a PlayFab ban via CloudScript | runs inside `/api/report` |
| **Dashboard** | Browser view of who is online and who is staff | `GET /dashboard`, `GET /api/dashboard` |

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
test_index.py             134 smoke tests, no credentials needed
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

It polls every 15s and stores the secret in `localStorage`.

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

## Tests

```
python test_index.py
```

134 checks covering auth, input validation, cooldowns, the PlayFab degradation
paths, map/game-mode/duration formatting, Discord embed shapes, the online
registry, the dashboard endpoints, the player-ID privacy regressions and the two
crash fixes above. Uses Flask's test client, so nothing leaves the machine and
no credentials are required.

All 134 pass.

**Not tested:** anything requiring real PlayFab credentials or a live Discord
webhook, and no run on a Quest device. The C# compiles clean against the
project's assemblies (exit 0), but that is a compile check, not a gameplay test.
