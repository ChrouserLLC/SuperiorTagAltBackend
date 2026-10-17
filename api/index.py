"""
Superior Tag Alt Backend
========================

One combined Flask service providing:

  * Player tracking  (lobby join/leave, online counts, Discord embeds)
  * Player reports   (in-game report -> Discord moderation channel)
  * Insta-ban        (report can trigger a PlayFab ban via CloudScript)
  * Redeem codes     (in-game REDEEM tab -> PlayFab catalog item)

Original work, merged from three separate single-purpose services into one
deployment. All three previously deployed to different Vercel projects and
shared the same shape (secret + JSON body + Discord webhook).

Run locally:  python api/index.py
Deploy:       Vercel (see vercel.json + README.md)
"""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

from flask import Flask, Response, jsonify, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PLAYFAB_TITLE_ID = os.environ.get("PLAYFAB_TITLE_ID", "12304A")
PLAYFAB_SECRET_KEY = os.environ.get("PLAYFAB_SECRET_KEY", "9U76KWPK7KPWTJNBDJ5AW4MDYGZ688C4XRQZBFYI33O7NZ7HTN")

# One shared secret for every client-facing endpoint. The original services each
# had their own (REPORT_SECRET / TRACKER_SECRET); a single value means the Unity
# side is configured once.
API_SECRET = os.environ.get("API_SECRET", "vqeQrzStXB1U7wpojlC8Yaewmsae6YAcs3nEXfHFUJt0co1176gPQddh4qAwdqDA")

TRACKER_WEBHOOK_URL = os.environ.get("TRACKER_WEBHOOK_URL", "https://discord.com/api/webhooks/1560351111045447710/Tcfm53ZBDwYT21O6J898iAgwfoLTyn-UjQ_Bme4evlGYb43ECXrlKVxb3yGGpR4LRTwy")
TRACKER_VIP_WEBHOOK_URL = os.environ.get("TRACKER_VIP_WEBHOOK_URL", "https://discord.com/api/webhooks/1560351193568645151/7tv986Faqocmpfp0xu0m3_J4dxvYaMyKnwekz_0EljhNq0N-wz9315WRNiKFoMtegupa")
REPORT_WEBHOOK_URL = os.environ.get("REPORT_WEBHOOK_URL", "https://discord.com/api/webhooks/1560351283498459297/Qa4Kc3XAvM8hia7xvtlxw5SG-xBzAuSaUzz055t17DePjIw-QkeWUfb767H1PMKOhYiL")

TRACKER_COOLDOWN_SECONDS = int(os.environ.get("TRACKER_COOLDOWN_SECONDS", "10"))
REPORT_COOLDOWN_SECONDS = int(os.environ.get("REPORT_COOLDOWN_SECONDS", "15"))

TRACKED_PLAYERS_KEY = os.environ.get("TRACKED_PLAYERS_KEY", "TrackedPlayers")

# How long a player stays in the dashboard's per-player list without a fresh
# event. The client only posts tracker events on join/leave, so this needs to
# be comfortably longer than a typical session or a full lobby will drop off
# the list while everyone is still playing. The authoritative number is the
# global count from /api/online-count; this list is best-effort detail.
ONLINE_PLAYER_TTL_SECONDS = int(os.environ.get("ONLINE_PLAYER_TTL_SECONDS", "900"))

# Redeem: which cosmetics are redeemable comes from catalog TAGS
# (redeem:CODE), not from here. The table below only holds per-code settings
# and currency rewards, so a code can be turned off or annotated without
# touching PlayFab. See REDEEM_TAG_PREFIX near the redeem section.
REDEEM_CODES_KEY = os.environ.get("REDEEM_CODES_KEY", "RedeemCodes")
# Which codes a player has already spent. Stored in the player's own private
# UserData rather than TitleData: one shared TitleData value would grow forever
# and eventually hit the TitleData size cap, silently losing redemption history.
REDEEM_USED_KEY = os.environ.get("REDEEM_USED_KEY", "RedeemUsed")
REDEEM_COOLDOWN_SECONDS = int(os.environ.get("REDEEM_COOLDOWN_SECONDS", "5"))
REDEEM_WEBHOOK_URL = os.environ.get("REDEEM_WEBHOOK_URL", "https://discord.com/api/webhooks/1560930877775679499/MWskoFRx4B6NPGvOC-kEw1pyZCtV6V-kP8lU5sMBxNOkRs6SrH88Cib9Ral1rLwsPPXF")

try:
    ROLE_EMOJIS = json.loads(os.environ.get("TRACKER_ROLE_EMOJIS", "{}"))
except (ValueError, TypeError):
    ROLE_EMOJIS = {}

TRACKED_CACHE_TTL_SECONDS = 60
ONLINE_GLOBAL_TTL_SECONDS = 90

# ---------------------------------------------------------------------------
# Static tables
# ---------------------------------------------------------------------------

TRACKER_EVENT_LABELS = {
    "joined_room": "Joined Lobby",
    "left_room": "Left Lobby",
    "player_joined": "Player Joined",
    "player_left": "Player Left",
}

TRACKER_ROLE_LABELS = {
    "moderator": "Moderator",
    "content_creator": "Content Creator",
    "admin": "Admin",
    "owner": "Owner",
    None: "Player",
}

TRACKER_ROLE_COLORS = {
    "moderator": 0x5865F2,
    "content_creator": 0xFEBD57,
    "admin": 0xED4245,
    "owner": 0x9B59B6,
    None: 0x4ADE80,
}

REPORT_REASONS = {
    "Cheating": "Cheating",
    "Toxicity": "Toxicity",
    "HateSpeech": "Hate Speech",
    "Bullying": "Bullying",
    "Doxing": "Doxing",
    "Impersonation": "Impersonation",
}

REPORT_COLORS = {
    "Cheating": 0xFF453A,
    "Toxicity": 0xFF9F0A,
    "HateSpeech": 0xBF5AF2,
    "Bullying": 0xFFD60A,
    "Doxing": 0xFF2D55,
    "Impersonation": 0x64D2FF,
}

MAP_NAMES = {
    "forest": "Forest",
    "cave": "Cave",
    "canyon": "Canyon",
    "city": "City",
    "mountain": "Mountain",
    "clouds": "Clouds",
    "skyjungle": "Sky Jungle",
    "basement": "Basement",
    "beach": "Beach",
    "ball": "Ball",
}

ZONE_MAP_NAMES = {
    "forest": "Forest",
    "city": "City",
    "basement": "Basement",
    "canyon": "Canyon",
    "beach": "Beach",
    "mountain": "Mountain",
    "skyjungle": "Sky Jungle",
    "cave": "Cave",
    "citywithskyjungle": "City with Sky Jungle",
    "tutorial": "Tutorial",
    "rotating": "Rotating",
}

SCENE_MAP_NAMES = {
    "GorillaTagSJR": "Main",
    "GorillaTag": "Main",
    "RankedMap": "Ranked",
    "Monkey-Blocks": "Monkey Blocks",
    "Metro": "Metro",
    "Hoverpark": "Hoverpark",
    "hatchery": "Hatchery",
    "Critters": "Critters",
    "Catacombs": "Catacombs",
}

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

_tracked_cache = None
_tracked_cache_at = 0.0
_tracker_cooldowns = {}
_report_cooldowns = {}
_redeem_cooldowns = {}
_cooldown_lock = threading.Lock()
_online_registry = {}
_online_lock = threading.Lock()
_online_global_count = 0
_online_global_at = 0.0
_redeem_codes_cache = None
_redeem_codes_cache_at = 0.0
_catalog_cache = None
_catalog_cache_at = 0.0
_redeem_index_cache = None
_redeem_index_cache_at = 0.0
_redeem_index_problems = []


# ---------------------------------------------------------------------------
# PlayFab
# ---------------------------------------------------------------------------

def pf_request(path, body):
    """Call a PlayFab server API endpoint.

    Returns (ok, result). Never raises: a missing configuration or a network
    fault must degrade to 'not verified', never to a 500.
    """
    if not PLAYFAB_TITLE_ID or not PLAYFAB_SECRET_KEY:
        # Building a URL with an empty title id raises UnicodeError from the
        # idna encoder, which previously escaped as a 500 and broke every
        # endpoint that touched PlayFab.
        return False, {"errorMessage": "PlayFab is not configured"}

    url = "https://{0}.playfabapi.com/Server/{1}".format(PLAYFAB_TITLE_ID, path)
    try:
        # The Request is built inside the try: a malformed title id makes
        # urllib raise ValueError from _parse, which previously escaped as a
        # 500 instead of degrading to "not verified".
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-SecretKey": PLAYFAB_SECRET_KEY,
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return True, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return False, json.loads(e.read().decode("utf-8"))
        except ValueError:
            return False, {"errorMessage": "HTTP {0}".format(e.code)}
    except urllib.error.URLError as e:
        return False, {"errorMessage": str(e.reason)}
    except Exception as e:
        return False, {"errorMessage": "{0}: {1}".format(type(e).__name__, e)}


def repair_tracked_players(raw):
    """Recover role lists from a malformed Title Data value."""
    result = {"content_creators": [], "moderators": [], "admins": [], "owners": []}
    for key in result:
        if key not in raw:
            continue
        start = raw.index(key)
        rest = raw[start + len(key):]
        end = rest.index("]") if "]" in rest else len(rest)
        result[key] = re.findall(r"[0-9A-Fa-f]{12,32}", rest[:end])
    return result


def empty_tracked():
    return {"content_creators": [], "moderators": [], "admins": [], "owners": []}


def load_tracked_players(force=False):
    global _tracked_cache, _tracked_cache_at
    now = time.time()
    if (force or _tracked_cache is None
            or now - _tracked_cache_at > TRACKED_CACHE_TTL_SECONDS):
        ok, result = pf_request("GetTitleData", {})
        if not ok:
            return _tracked_cache or empty_tracked()
        raw = (result.get("data") or {}).get("Data") or {}
        value = raw.get(TRACKED_PLAYERS_KEY) or ""
        if not value:
            data = empty_tracked()
        else:
            try:
                data = json.loads(value)
            except (ValueError, TypeError):
                data = repair_tracked_players(value)
        data = data or {}
        for key in ("content_creators", "moderators", "admins", "owners"):
            data.setdefault(key, [])
        _tracked_cache = data
        _tracked_cache_at = now
    return _tracked_cache or empty_tracked()


def lookup_role(playfab_id):
    if not playfab_id:
        return None
    data = load_tracked_players()
    role_keys = {
        "owners": "owner",
        "admins": "admin",
        "moderators": "moderator",
        "content_creators": "content_creator",
    }
    for key, role in role_keys.items():
        for entry in data.get(key) or []:
            if isinstance(entry, str):
                if entry == playfab_id:
                    return role
            elif isinstance(entry, dict) and entry.get("playFabId") == playfab_id:
                return role
    return None


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------

DISCORD_USER_AGENT = os.environ.get(
    "DISCORD_USER_AGENT",
    "SuperiorTagAlt/1.0 (+https://superiortagaltbackend.vercel.app)")


def post_webhook(url, payload):
    if not url:
        return False, "unset"
    try:
        # Built inside the try: urllib raises ValueError on an unknown URL type
        # (e.g. a webhook pasted without "https://"), which would otherwise
        # escape as a 500.
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={
                "Content-Type": "application/json",
                # Required. Without an explicit User-Agent, urllib sends
                # "Python-urllib/3.x", and Discord's Cloudflare fingerprinting
                # rejects it with HTTP 403 error code 1010 ("banned based on
                # your browser's signature"). Every embed silently failed.
                "User-Agent": DISCORD_USER_AGENT,
            })
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204), "status {0}".format(resp.status)
    except urllib.error.HTTPError as e:
        return e.code in (200, 204), "http {0}".format(e.code)
    except urllib.error.URLError as e:
        return False, "urlerror: {0}".format(e.reason)
    except Exception as e:
        return False, "{0}: {1}".format(type(e).__name__, e)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def role_emoji(role):
    emojis = ROLE_EMOJIS.get(role) or []
    if not emojis:
        return ""
    return emojis[int(time.time() / 3600) % len(emojis)]


def format_game_mode(raw):
    if not raw:
        return None
    modes = {
        "INFECTION": "Infection", "HUNT": "Hunt", "CASUAL": "Casual",
        "BATTLE": "Battle", "CTF": "Capture the Flag",
        "PURSUIT": "Pursuit", "PAINTBRAWL": "Paint Brawl",
        "GUARDIAN": "Guardian", "PVE": "PVE", "TAG": "Tag",
        "ROBOTCREEP": "Robot Creep",
    }
    upper = raw.upper()
    for key, label in modes.items():
        if key in upper:
            return label
    return raw


def format_map(game_mode, scene, zone=None):
    if zone:
        lowered = zone.lower()
        for key, label in ZONE_MAP_NAMES.items():
            if key in lowered:
                return label
    if game_mode:
        lowered = game_mode.lower()
        for key, label in MAP_NAMES.items():
            if key in lowered:
                return label
    if scene:
        lowered = scene.lower()
        for key, label in SCENE_MAP_NAMES.items():
            if key.lower() in lowered:
                return label
        return scene
    return None


def format_duration(seconds):
    if seconds is None or seconds < 0:
        return None
    seconds = int(seconds)
    if seconds < 60:
        return "{0}s".format(seconds)
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return "{0}m {1}s".format(minutes, secs)
    hours, mins = divmod(minutes, 60)
    return "{0}h {1}m".format(hours, mins)


def lobby_bar(player_count, max_players):
    max_players = max(1, max_players or 10)
    count = max(0, min(int(player_count or 0), max_players))
    bar = "\u2593" * count + "\u2591" * (max_players - count)
    return "{0}  {1}/{2}".format(bar, count, max_players)


# ---------------------------------------------------------------------------
# Embeds
# ---------------------------------------------------------------------------

def build_tracker_embed(event, room, player_count, max_players, player_name,
                        playfab_id, role, game_mode, region, platform, players,
                        seconds_in_lobby, scene, vip=False):
    label = TRACKER_EVENT_LABELS.get(event, "Lobby Event")
    role_label = TRACKER_ROLE_LABELS.get(role, "Player")
    emoji = role_emoji(role)
    role_display = "{0} **{1}**".format(emoji, role_label).strip()
    player_display = (player_name or "Unknown")[:100]
    pfid = (playfab_id or "Unknown")[:64]
    room_display = (room or "Unknown")[:100]
    verb = "left" if "left" in event else "joined"

    fields = [
        {"name": "Player", "value": player_display, "inline": True},
        {"name": "Role", "value": role_display, "inline": True},
        {"name": "PlayFab ID", "value": "`{0}`".format(pfid), "inline": True},
        {"name": "Lobby", "value": lobby_bar(player_count, max_players), "inline": False},
    ]

    mode_label = format_game_mode(game_mode)
    if mode_label:
        fields.append({"name": "Game Mode", "value": mode_label, "inline": True})
    map_label = format_map(game_mode, scene)
    if map_label:
        fields.append({"name": "Map", "value": map_label, "inline": True})
    if region:
        fields.append({"name": "Region", "value": region, "inline": True})
    if platform:
        fields.append({"name": "Platform", "value": platform, "inline": True})
    duration = format_duration(seconds_in_lobby)
    if duration:
        fields.append({"name": "Time in Lobby", "value": duration, "inline": True})

    player_names = [p[:60] for p in (players or []) if p]
    if player_names:
        fields.append({
            "name": "Players in Lobby ({0})".format(len(player_names)),
            "value": ", ".join(player_names)[:1020] or "None",
            "inline": False,
        })

    embed = {
        "title": label,
        "description": "**{0}** {1} **{2}**".format(player_display, verb, room_display),
        "color": TRACKER_ROLE_COLORS.get(role),
        "fields": fields,
        "footer": {"text": "Superior Tag Alt"},
    }
    if vip:
        embed["title"] = "{0} {1}".format(emoji, label).strip()
        embed["author"] = {"name": "{0} Tracker".format(role_label)}
        embed["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    return {"embeds": [embed]}


def build_report_embed(reason, room_code, is_private, game_mode, scene, map_label,
                       reporter_name, reporter_id, reported_name, reported_id,
                       room_count=None):
    reason_label = REPORT_REASONS.get(reason, reason or "Unknown")
    visibility = "Private" if is_private else "Public"
    if room_code == "-PRIVATE-":
        visibility = "Private"
        room_code = "(hidden)"
    elif not room_code:
        room_code = "(unknown)"

    description = "**{0}** reported **{1}** for **{2}**".format(
        reporter_name or "Unknown", reported_name or "Unknown", reason_label)

    fields = [
        {"name": "Reported Player", "value": (reported_name or "Unknown")[:100], "inline": True},
        {"name": "Reported PlayFab ID", "value": "`{0}`".format((reported_id or "Unknown")[:64]), "inline": True},
        {"name": "Reason", "value": reason_label, "inline": True},
        {"name": "Reporter", "value": (reporter_name or "Unknown")[:100], "inline": True},
        {"name": "Reporter PlayFab ID", "value": "`{0}`".format((reporter_id or "Unknown")[:64]), "inline": True},
        {"name": "Visibility", "value": visibility, "inline": True},
        {"name": "Room Code", "value": "`{0}`".format(room_code[:50]), "inline": False},
    ]
    if game_mode:
        fields.append({"name": "Game Mode", "value": game_mode, "inline": True})
    if map_label:
        fields.append({"name": "Map", "value": map_label, "inline": True})
    fields.append({"name": "Players in Room",
                   "value": str(int(room_count)) if room_count is not None else "?",
                   "inline": True})

    return {"embeds": [{
        "title": "New Player Report",
        "description": description,
        "color": REPORT_COLORS.get(reason, 0xFF453A),
        "fields": fields[:25],
        "footer": {"text": "Superior Tag Alt"},
    }]}


def build_ban_embed(instaban, body, reason):
    fields = [
        {"name": "Banned Player", "value": body.get("reported_name") or "Unknown", "inline": True},
        {"name": "Banned PlayFab ID", "value": "`{0}`".format(body.get("reported_id") or "Unknown"), "inline": True},
        {"name": "Ban Duration", "value": "**{0}h**".format(instaban.get("hours", 24)), "inline": True},
        {"name": "Reason", "value": reason or "Unknown", "inline": True},
        {"name": "Banned By", "value": body.get("reporter_name") or "Unknown", "inline": True},
    ]
    return {"embeds": [{
        "title": "INSTA-BAN",
        "color": 0xFF453A,
        "fields": fields,
        "footer": {"text": "Superior Tag Alt"},
    }]}


# ---------------------------------------------------------------------------
# Online registry
# ---------------------------------------------------------------------------

def touch_online(player_key, player_name=""):
    if not player_key or player_key == "unknown":
        return
    with _online_lock:
        # Keep the display name alongside the ID. Storing only the timestamp
        # meant the dashboard had nothing to show but truncated PlayFab IDs.
        previous = _online_registry.get(player_key) or {}
        previous["name"] = player_name or previous.get("name") or ""
        previous["at"] = time.time()
        _online_registry[player_key] = previous


def untouch_online(player_key):
    if not player_key or player_key == "unknown":
        return
    with _online_lock:
        _online_registry.pop(player_key, None)


def online_snapshot():
    """Live players as a list of {'playfab_id', 'name'}, oldest activity pruned."""
    now = time.time()
    with _online_lock:
        expired = [k for k, entry in _online_registry.items()
                   if now - entry.get("at", 0) > ONLINE_PLAYER_TTL_SECONDS]
        for k in expired:
            _online_registry.pop(k, None)
        return sorted(
            ({"playfab_id": k, "name": entry.get("name") or ""}
             for k, entry in _online_registry.items()),
            key=lambda row: row["playfab_id"],
        )


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def check_secret(body):
    return (body.get("secret") or "").strip() == API_SECRET


def check_secret_request():
    """Auth for GET endpoints.

    Accepts the secret either in the JSON body (the Unity client's convention)
    or in an X-Api-Secret header. The header form exists so the browser
    dashboard does not have to put the secret in a query string, where it would
    end up in server logs and browser history.
    """
    body = request.get_json(silent=True) or {}
    candidate = (body.get("secret") or "").strip()
    if not candidate:
        candidate = (request.headers.get("X-Api-Secret") or "").strip()
    return bool(candidate) and candidate == API_SECRET


# ---------------------------------------------------------------------------
# Cooldown helper
# ---------------------------------------------------------------------------

def hit_cooldown(store, key, cooldown_seconds):
    """Returns (allowed, retry_after_seconds)."""
    with _cooldown_lock:
        now = time.time()
        last = store.get(key, 0)
        if now - last < cooldown_seconds:
            return False, int(cooldown_seconds - (now - last))
        store[key] = now
        if len(store) > 1000:
            cutoff = now - cooldown_seconds * 2
            for k in [k for k, t in store.items() if t < cutoff]:
                store.pop(k, None)
        return True, 0


# ---------------------------------------------------------------------------
# Insta-ban
# ---------------------------------------------------------------------------

def run_instaban(reporter_id, reported_id, reason):
    """Ask the PlayFab CloudScript to ban the reported player.

    Authorisation lives in the CloudScript (INSTABAN_REPORTERS allowlist), not
    here. A failed call reports 'banned: False' rather than raising.
    """
    if not reported_id or not reporter_id:
        return {"checked": True, "banned": False, "reason": "missing ids"}
    if not PLAYFAB_TITLE_ID or not PLAYFAB_SECRET_KEY:
        return {"checked": False, "banned": False,
                "reason": "PlayFab is not configured"}

    ok, result = pf_request("ExecuteCloudScript", {
        "PlayFabId": reporter_id,
        "FunctionName": "InstaBanReport",
        "FunctionParameter": {
            "reportedPlayFabId": reported_id,
            "reporterPlayFabId": reporter_id,
            "reason": reason or "",
        },
        "GeneratePlayStreamEvent": True,
    })
    if not ok:
        return {
            "checked": True,
            "banned": False,
            "message": result.get("errorMessage") or "cloudscript call failed",
        }
    fn = (result.get("data") or {}).get("FunctionResult") or {}
    return {
        "checked": True,
        "banned": bool(fn.get("banned")),
        "message": fn.get("reason") or fn.get("message") or "ok",
        "banId": fn.get("banId"),
        "bannedPlayFabId": fn.get("bannedPlayFabId"),
        "hours": fn.get("hours", 24),
    }


# ---------------------------------------------------------------------------
# Routes: reports + insta-ban
# ---------------------------------------------------------------------------

@app.route("/api/report", methods=["POST"])
def report():
    body = request.get_json(silent=True) or {}
    if not check_secret(body):
        return jsonify({"success": False, "error": "bad secret"}), 401

    reason = (body.get("reason") or "").strip()
    room_code = (body.get("room_code") or "").strip()
    is_private = bool(body.get("is_private", False))
    game_mode = (body.get("game_mode") or "").strip()
    scene = (body.get("scene") or "").strip()
    zone = (body.get("zone") or "").strip()
    raw_room_count = body.get("room_count")
    try:
        room_count = int(raw_room_count) if raw_room_count is not None else None
    except (TypeError, ValueError):
        room_count = None
    reporter_name = (body.get("reporter_name") or "").strip()
    reporter_id = (body.get("reporter_id") or "").strip()
    reported_name = (body.get("reported_name") or "").strip()
    reported_id = (body.get("reported_id") or "").strip()

    if not reason or reason not in REPORT_REASONS:
        return jsonify({"success": False, "error": "invalid reason"}), 400
    if not reported_name and not reported_id:
        return jsonify({"success": False,
                        "error": "reported_name or reported_id required"}), 400

    allowed, retry_after = hit_cooldown(
        _report_cooldowns,
        "{0}|{1}".format(reporter_id or reporter_name or "unknown",
                         reported_id or reported_name or "unknown"),
        REPORT_COOLDOWN_SECONDS)
    if not allowed:
        return jsonify({
            "success": False,
            "error": "cooldown",
            "retry_after_seconds": retry_after,
        }), 429

    map_label = format_map(game_mode, scene, zone)

    # Insta-ban first so the report embed can note the outcome.
    instaban = run_instaban(reporter_id, reported_id, reason)
    if instaban.get("banned"):
        post_webhook(REPORT_WEBHOOK_URL, build_ban_embed(instaban, body, reason))

    payload = build_report_embed(reason, room_code, is_private, game_mode, scene,
                                 map_label, reporter_name, reporter_id,
                                 reported_name, reported_id, room_count)
    sent, err = post_webhook(REPORT_WEBHOOK_URL, payload)

    return jsonify({
        "success": sent,
        "reason": reason,
        "webhook_sent": sent,
        "webhook_error": err,
        "reporter": reporter_name,
        "reported": reported_name,
        "room_code": room_code,
        "is_private": is_private,
        "room_count": room_count,
        "zone": zone,
        "map": map_label,
        "instaban": instaban,
    })


# ---------------------------------------------------------------------------
# Routes: player tracker
# ---------------------------------------------------------------------------

@app.route("/api/tracker", methods=["POST"])
def tracker():
    body = request.get_json(silent=True) or {}
    if not check_secret(body):
        return jsonify({"success": False, "error": "bad secret"}), 401

    event = (body.get("event") or "").strip()
    room = (body.get("room") or "").strip()
    player_name = (body.get("player_name") or "").strip()
    playfab_id = (body.get("playfab_id") or "").strip()
    game_mode = (body.get("game_mode") or "").strip()
    scene = (body.get("scene") or "").strip()
    region = (body.get("region") or "").strip()
    platform = (body.get("platform") or "").strip()
    players = body.get("players")
    if not isinstance(players, list):
        players = []
    raw_seconds = body.get("seconds_in_lobby")
    try:
        seconds_in_lobby = int(raw_seconds) if raw_seconds is not None else -1
    except (TypeError, ValueError):
        seconds_in_lobby = -1
    try:
        player_count = int(body.get("player_count") or 0)
        max_players = int(body.get("max_players") or 0)
    except (TypeError, ValueError):
        player_count = 0
        max_players = 0

    if event not in TRACKER_EVENT_LABELS:
        return jsonify({"success": False, "error": "unknown event"}), 400
    if not player_name and not playfab_id:
        return jsonify({"success": False,
                        "error": "player_name or playfab_id required"}), 400

    role = lookup_role(playfab_id)

    online_key = playfab_id or player_name
    if "left" in event:
        untouch_online(online_key)
    else:
        touch_online(online_key, player_name)

    allowed, retry_after = hit_cooldown(
        _tracker_cooldowns,
        "{0}|{1}|{2}".format(event, playfab_id or player_name or "unknown",
                              room or ""),
        TRACKER_COOLDOWN_SECONDS)
    if not allowed:
        return jsonify({
            "success": False,
            "error": "cooldown",
            "retry_after_seconds": retry_after,
            "role": role,
        }), 429

    kwargs = {
        "event": event,
        "room": room,
        "player_count": player_count,
        "max_players": max_players,
        "player_name": player_name,
        "playfab_id": playfab_id,
        "role": role,
        "game_mode": game_mode,
        "region": region,
        "platform": platform,
        "players": players,
        "seconds_in_lobby": seconds_in_lobby,
        "scene": scene,
    }

    if role is not None:
        sent_vip, err_vip = post_webhook(
            TRACKER_VIP_WEBHOOK_URL, build_tracker_embed(vip=True, **kwargs))
        sent_all, err_all = False, None
    else:
        sent_all, err_all = post_webhook(
            TRACKER_WEBHOOK_URL, build_tracker_embed(vip=False, **kwargs))
        sent_vip, err_vip = False, None

    return jsonify({
        "success": True,
        "role": role,
        "webhook_sent": sent_all,
        "vip_webhook_sent": sent_vip,
        "webhook_error": err_all,
        "vip_webhook_error": err_vip,
        "lobby": "{0}/{1}".format(player_count, max_players),
    })


# ---------------------------------------------------------------------------
# Redeem codes
# ---------------------------------------------------------------------------
#
# A code points at a reward two ways:
#
#   1. Cosmetics  - tag the catalog item with "redeem:CODE" in the PlayFab
#                   dashboard. The backend scans the catalog for that tag, so you
#                   never copy an Item ID anywhere.
#   2. Currency   - PlayFab virtual currency (this title uses SR and RM). These
#                   have no catalog item to tag, so they are declared in the
#                   settings table below.
#
# The settings table (PlayFab TitleData, key RedeemCodes) holds only *how* a code
# behaves - enabled, max_uses, note - never *what* it gives for a cosmetic. That
# keeps the catalog the single source of truth for cosmetics:
#
#   {
#     "BETA":   {"enabled": true, "max_uses": 0, "note": "announcement"},
#     "GOLD":   {"reward_type": "currency", "reward_id": "SR",
#                "amount": 5000, "reward_label": "5000 SHINY ROCKS",
#                "enabled": true, "note": ""}
#   }
#
# Why Tags and not Custom Data: the legacy DLC catalog does not expose Custom
# Data through any PlayFab API the server can reach. Server/GetCatalogItems
# omits the field entirely, Server/GetCatalogItem 404s, and the catalog is not
# in TitleData. Tags ARE returned, so they are the only marker that works.

REDEEM_REWARD_TYPES = ("cosmetic", "currency")

# Custom tag prefix an item must carry to be redeemable, e.g. "redeem:BETA".
REDEEM_TAG_PREFIX = "redeem:"

# PlayFab caps a TitleData value at 4000 bytes. Refuse to save past that rather
# than letting PlayFab silently truncate the table into unparseable JSON.
REDEEM_CODES_MAX_BYTES = 3800

REDEEM_CATALOG_CACHE_TTL_SECONDS = 60
REDEEM_CODES_CACHE_TTL_SECONDS = 30


# --- item id helpers ------------------------------------------------------

def _strip_trailing_dot(item_id):
    """PlayFab's legacy DLC catalog stores cosmetic ids with a trailing dot
    ("LBAAC.") while the game uses them without ("LBAAC"). Normalise so a code
    works whichever spelling you type. Only ONE dot is stripped, because "..."
    is itself a real ItemId in this catalog.
    """
    if item_id.endswith("."):
        return item_id[:-1]
    return item_id


# --- catalog --------------------------------------------------------------

def load_catalog(force=False):
    """Fetch the DLC catalog. Never raises; returns [] on failure.

    ~1300 items / ~400KB and ~0.4s to fetch, so it is cached. A failed fetch
    returns the previous cache rather than wiping the code index, because
    "no codes available" for a minute is worse than briefly-stale codes.
    """
    global _catalog_cache, _catalog_cache_at
    now = time.time()
    if (not force and _catalog_cache is not None
            and now - _catalog_cache_at <= REDEEM_CATALOG_CACHE_TTL_SECONDS):
        return _catalog_cache

    ok, result = pf_request("GetCatalogItems", {
        "CatalogVersion": "DLC",
        "Etag": "",
    })
    if not ok:
        return _catalog_cache or []
    catalog = ((result.get("data") or {}).get("Catalog")) or []
    _catalog_cache = catalog
    _catalog_cache_at = now
    return catalog


def load_redeem_index(force=False):
    """{CODE: reward} built from catalog items tagged redeem:CODE.

    Returns (index, problems) so the caller can surface duplicate tags instead
    of silently picking one item.
    """
    global _redeem_index_cache, _redeem_index_cache_at, _redeem_index_problems
    now = time.time()
    if (not force and _redeem_index_cache is not None
            and now - _redeem_index_cache_at <= REDEEM_CODES_CACHE_TTL_SECONDS):
        return _redeem_index_cache, _redeem_index_problems

    index = {}
    problems = []
    for item in load_catalog():
        if not isinstance(item, dict):
            continue
        item_id = item.get("ItemId") or ""
        if not item_id:
            continue
        for tag in item.get("Tags") or []:
            if not isinstance(tag, str):
                continue
            tag = tag.strip()
            if not tag.lower().startswith(REDEEM_TAG_PREFIX):
                continue
            code = tag[len(REDEEM_TAG_PREFIX):].strip().upper()
            if not code:
                problems.append("item {0} has a bare 'redeem:' tag".format(item_id))
                continue
            if code in index:
                problems.append(
                    "code {0} is claimed by both {1} and {2}".format(
                        code, index[code]["reward_id"], item_id))
                continue
            index[code] = {
                "reward_type": "cosmetic",
                "reward_id": item_id,
                # DisplayName is empty on every legacy DLC item, so fall back to
                # the id. Set reward_label in the settings table for a nicer one.
                "reward_label": (item.get("DisplayName") or "").strip() or item_id,
                "amount": 0,
                "source": "catalog_tag",
            }

    _redeem_index_cache = index
    _redeem_index_problems = problems
    _redeem_index_cache_at = now
    return index, problems


def resolve_catalog_item_id(item_id):
    """Map a possibly-dot-less ItemId onto the catalog's real spelling."""
    if not item_id:
        return None
    wanted = _strip_trailing_dot(item_id.strip())
    for item in load_catalog():
        candidate = item.get("ItemId") or ""
        if candidate == item_id or _strip_trailing_dot(candidate) == wanted:
            return candidate
    return None


# --- settings table -------------------------------------------------------

def _normalise_settings_table(raw):
    """Coerce TitleData into {CODE: settings}. Rewards for cosmetics are left
    to the catalog; only currency entries carry reward_type/reward_id."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    if not isinstance(raw, dict):
        return {}

    table = {}
    for code, entry in raw.items():
        if not isinstance(code, str):
            continue
        code = code.strip().upper()
        if not code:
            continue
        if not isinstance(entry, dict):
            entry = {}

        reward_type = str(entry.get("reward_type") or "").strip().lower()
        if reward_type and reward_type not in REDEEM_REWARD_TYPES:
            reward_type = ""
        try:
            # "credits" is accepted as a legacy alias so an older settings blob
            # keeps working.
            amount = int(entry.get("amount") or entry.get("credits") or 0)
        except (TypeError, ValueError):
            amount = 0
        try:
            max_uses = int(entry.get("max_uses") or 0)
        except (TypeError, ValueError):
            max_uses = 0

        reward_id = str(entry.get("reward_id") or "").strip()
        # Infer the type only when it was not stated. An amount means currency
        # (this title uses SR and RM); otherwise a bare id is treated as a
        # catalog item, which is the historical shape.
        if not reward_type and reward_id:
            reward_type = "currency" if amount > 0 else "cosmetic"
        if reward_type == "currency" and not reward_id:
            reward_type = ""

        table[code] = {
            "reward_type": reward_type,
            "reward_id": reward_id,
            "reward_label": str(entry.get("reward_label") or "").strip(),
            "amount": max(0, amount),
            "max_uses": max(0, max_uses),
            "enabled": entry.get("enabled", True) is not False,
            "note": str(entry.get("note") or ""),
        }
    return table


def load_settings(force=False):
    global _redeem_codes_cache, _redeem_codes_cache_at
    now = time.time()
    if (not force and _redeem_codes_cache is not None
            and now - _redeem_codes_cache_at <= REDEEM_CODES_CACHE_TTL_SECONDS):
        return _redeem_codes_cache

    table = {}
    ok, result = pf_request("GetTitleData", {})
    if ok:
        value = ((result.get("data") or {}).get("Data") or {}).get(REDEEM_CODES_KEY)
        table = _normalise_settings_table(value)

    _redeem_codes_cache = table
    if not table:
        # Never cache an empty table. It means "not configured yet" or a
        # transient PlayFab failure, and caching it would hide codes that were
        # just added for the whole TTL.
        _redeem_codes_cache_at = 0.0
    else:
        _redeem_codes_cache_at = now
    return table


def save_settings(table):
    encoded = json.dumps(table)
    if len(encoded.encode("utf-8")) > REDEEM_CODES_MAX_BYTES:
        return False, {"errorMessage": "settings table is too large for TitleData"}
    ok, result = pf_request("SetTitleData", {
        "Key": REDEEM_CODES_KEY,
        "Value": encoded,
    })
    load_settings(force=True)
    return ok, result


def resolve_code(code):
    """Merge catalog tag + settings into one entry, or None if unknown.

    The catalog wins for cosmetics: a table entry cannot point a cosmetic code
    at a different item, so marking an item is the only way to decide what a
    cosmetic code gives.
    """
    code = (code or "").strip().upper()
    if not code:
        return None
    settings = load_settings().get(code) or {}
    tagged, _ = load_redeem_index()
    from_tag = tagged.get(code)

    entry = dict(settings)
    if from_tag:
        entry["reward_type"] = "cosmetic"
        entry["reward_id"] = from_tag["reward_id"]
        if not entry.get("reward_label"):
            entry["reward_label"] = from_tag["reward_label"]
        entry["source"] = "catalog_tag"
    elif not entry.get("reward_type"):
        return None
    else:
        entry["source"] = "settings"

    # Cosmetic rewards must name an item that really exists, otherwise the grant
    # would fail later with a confusing PlayFab error.
    if entry.get("reward_type") == "cosmetic" and not entry.get("reward_id"):
        return None
    entry.setdefault("max_uses", 0)
    entry.setdefault("enabled", True)
    return entry


def list_codes():
    """Every known code: catalog-tagged cosmetics plus table entries."""
    tagged, problems = load_redeem_index(force=True)
    settings = load_settings(force=True)
    merged = {}
    for code in set(list(tagged.keys()) + list(settings.keys())):
        entry = resolve_code(code)
        if entry:
            merged[code] = entry
    return merged, problems


# --- redemption history ---------------------------------------------------

def get_player_redeemed(playfab_id):
    """Codes this player has already spent. Never raises."""
    if not playfab_id:
        return []
    ok, result = pf_request("GetUserData", {
        "PlayFabId": playfab_id,
        "Keys": [REDEEM_USED_KEY],
    })
    if not ok:
        return []
    value = ((result.get("data") or {}).get("Data") or {}).get(REDEEM_USED_KEY)
    if not value:
        return []
    try:
        value = json.loads(value)
    except (ValueError, TypeError):
        return []
    if not isinstance(value, list):
        return []
    return [str(v).strip().upper() for v in value]


def mark_player_redeemed(playfab_id, code, already_used):
    used = list(already_used)
    # Append unconditionally: a code with max_uses > 1 is meant to appear more
    # than once, and the duplicate is what the limit is counted against.
    used.append(code)
    ok, result = pf_request("UpdateUserData", {
        "PlayFabId": playfab_id,
        "Data": {REDEEM_USED_KEY: json.dumps(used)},
        "Permission": "Private",
    })
    return ok, result


# --- grants ---------------------------------------------------------------

def grant_cosmetic(playfab_id, item_id):
    """Give a PlayFab catalog item. Never raises."""
    if not playfab_id or not item_id:
        return False, {"errorMessage": "playfab_id and item_id required"}
    # Resolve to the catalog's own spelling so a dot-less id still resolves.
    resolved = resolve_catalog_item_id(item_id)
    if not resolved:
        return False, {"errorMessage": "no catalog item matches {0}".format(item_id)}
    return pf_request("GrantCatalogItem", {
        "PlayFabId": playfab_id,
        "ItemId": resolved,
        "Labels": ["redeem"],
    })


def grant_currency(playfab_id, currency_code, amount):
    """Add PlayFab virtual currency. Never raises.

    Uses the legacy AddUserVirtualCurrency because ExecuteInventoryApi 404s on
    this title (PlayFab calls that 404 with no body, which is how an
    un-migrated title answers it). VirtualCurrency and Amount are strings.
    """
    if not playfab_id or not currency_code:
        return False, {"errorMessage": "playfab_id and currency code required"}
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return False, {"errorMessage": "amount must be a number"}
    if amount <= 0:
        return False, {"errorMessage": "amount must be greater than zero"}
    return pf_request("AddUserVirtualCurrency", {
        "PlayFabId": playfab_id,
        "VirtualCurrency": currency_code,
        "Amount": str(amount),
    })


def grant_reward(playfab_id, entry):
    if entry.get("reward_type") == "currency":
        return grant_currency(playfab_id, entry.get("reward_id"),
                              entry.get("amount"))
    return grant_cosmetic(playfab_id, entry.get("reward_id"))


# --- discord --------------------------------------------------------------

def build_redeem_embed(code, entry, playfab_id, granted):
    fields = [
        {"name": "Code", "value": "`{0}`".format(code[:64]), "inline": True},
        {"name": "Reward", "value": (entry.get("reward_label") or "-")[:100], "inline": True},
        {"name": "Type", "value": entry.get("reward_type", "cosmetic"), "inline": True},
    ]
    if entry.get("reward_id"):
        fields.append({
            "name": "Item Id" if entry.get("reward_type") != "currency" else "Currency",
            "value": "`{0}`".format(entry["reward_id"][:64]),
            "inline": True,
        })
    if entry.get("amount"):
        fields.append({"name": "Amount", "value": str(entry["amount"]), "inline": True})
    fields.append({
        "name": "PlayFab ID",
        "value": "`{0}`".format((playfab_id or "Unknown")[:64]),
        "inline": False,
    })
    return {"embeds": [{
        "title": "Code Redeemed" if granted else "Code Rejected",
        "description": "`{0}` redeemed by `{1}`".format(code[:64], (playfab_id or "Unknown")[:40]),
        "color": 0x4ADE80 if granted else 0xFF453A,
        "fields": fields,
        "footer": {"text": "Superior Tag Alt"},
    }]}


def _redeem_reject(message, status=200, error=None):
    payload = {
        "success": False,
        "message": message,
        "reward_type": "",
        "reward_id": "",
        "reward_label": "",
        "amount": 0,
    }
    if error:
        payload["error"] = str(error)[:200]
    return jsonify(payload), status


# --- routes ---------------------------------------------------------------

@app.route("/api/redeem", methods=["POST"])
def redeem():
    """A player entered a code on the in-game REDEEM tab."""
    body = request.get_json(silent=True) or {}
    if not check_secret(body):
        return jsonify({"success": False, "message": "UNAUTHORISED."}), 401

    code = str(body.get("code") or "").strip().upper()
    playfab_id = str(body.get("playfab_id") or "").strip()
    platform = str(body.get("platform") or "").strip()

    if not code:
        return _redeem_reject("TYPE A CODE FIRST.", 400)
    if not playfab_id:
        # No PlayFab ID means no account to grant to and nowhere to record that
        # the code was spent. Refuse rather than grant to nobody.
        return _redeem_reject("SIGN IN BEFORE REDEEMING A CODE.", 400)

    allowed, retry_after = hit_cooldown(
        _redeem_cooldowns, "{0}|{1}".format(playfab_id, code),
        REDEEM_COOLDOWN_SECONDS)
    if not allowed:
        return _redeem_reject(
            "WAIT {0} SECONDS AND TRY AGAIN.".format(retry_after), 429)

    entry = resolve_code(code)
    if not entry:
        return _redeem_reject("CODE NOT RECOGNISED.")
    if not entry.get("enabled"):
        return _redeem_reject("THAT CODE IS NO LONGER ACTIVE.")

    already_used = get_player_redeemed(playfab_id)
    already_count = already_used.count(code)
    max_uses = entry.get("max_uses", 0)
    if max_uses:
        # max_uses is per player: they may claim the reward that many times.
        if already_count >= max_uses:
            return _redeem_reject("YOU HAVE ALREADY USED THAT CODE.")
    elif code in already_used:
        # Default: strictly one reward per player per code.
        return _redeem_reject("YOU HAVE ALREADY USED THAT CODE.")

    granted, grant_error = grant_reward(playfab_id, entry)
    if not granted:
        # Deliberately do NOT burn the code here: the grant failed, so the
        # player should be able to retry once PlayFab is reachable.
        detail = (grant_error or {}).get("errorMessage") or "grant failed"
        print("[redeem] grant failed for {0} -> {1}: {2}".format(
            code, playfab_id, detail))
        return _redeem_reject(
            "COULD NOT GRANT THE REWARD. TRY AGAIN LATER.", 502, detail)

    # Record the spend only after the grant succeeded, so a failed grant stays
    # retryable.
    mark_player_redeemed(playfab_id, code, already_used)

    webhook_sent, webhook_error = post_webhook(
        REDEEM_WEBHOOK_URL,
        build_redeem_embed(code, entry, playfab_id, True))

    return jsonify({
        "success": True,
        "message": "CODE ACCEPTED.",
        "code": code,
        "reward_type": entry.get("reward_type", "cosmetic"),
        "reward_id": entry.get("reward_id", ""),
        "reward_label": entry.get("reward_label", ""),
        "amount": entry.get("amount", 0),
        "platform": platform,
        "webhook_sent": webhook_sent,
        "webhook_error": webhook_error,
    })


@app.route("/api/redeem-codes", methods=["GET"])
def redeem_codes_list():
    if not check_secret_request():
        return jsonify({"success": False, "error": "bad secret"}), 401
    codes, problems = list_codes()
    return jsonify({
        "success": True,
        "codes": codes,
        "problems": problems,
        "tag_prefix": REDEEM_TAG_PREFIX,
    })


@app.route("/api/redeem-codes", methods=["POST"])
def redeem_codes_upsert():
    """Change how a code behaves.

    Cosmetics are NOT created here. To make a cosmetic redeemable you tag its
    catalog item with "<REDEEM_TAG_PREFIX><CODE>"; this endpoint only holds the
    settings, or declares a currency reward (which has no item to tag).
    """
    body = request.get_json(silent=True) or {}
    if not check_secret(body):
        return jsonify({"success": False, "error": "bad secret"}), 401

    code = str(body.get("code") or "").strip().upper()
    if not code:
        return jsonify({"success": False, "error": "code required"}), 400

    tagged, _ = load_redeem_index()
    settings = load_settings(force=True)
    from_tag = tagged.get(code)

    if body.get("delete"):
        if code not in settings:
            return jsonify({
                "success": False,
                "error": "no settings for that code (catalog tags are removed in PlayFab)",
            }), 404
        settings.pop(code, None)
        ok, result = save_settings(settings)
        if not ok:
            return jsonify({
                "success": False,
                "error": (result or {}).get("errorMessage") or "could not save",
            }), 502
        return jsonify({"success": True, "code": code})

    merged = dict(settings.get(code) or {})

    # Accept reward_type/reward_id only for currency. A cosmetic's reward comes
    # from the catalog tag, so allowing them here would create a second source
    # of truth that could silently disagree with the tag.
    for key in ("reward_type", "reward_id", "reward_label", "note", "enabled"):
        if key in body:
            merged[key] = body[key]
    for key in ("amount", "max_uses"):
        if key in body:
            merged[key] = body[key]

    normalised = _normalise_settings_table({code: merged}).get(code) or {}
    reward_type = (normalised.get("reward_type") or "").strip().lower()
    reward_id = (normalised.get("reward_id") or "").strip()

    if not from_tag:
        # No catalog item claims this code, so the table has to supply the whole
        # reward. Anything missing here is a bad request, not a broken code.
        if not reward_type:
            return jsonify({
                "success": False,
                "error": "unknown code - tag a catalog item '{0}{1}', "
                         "or send reward_type=currency with reward_id".format(
                             REDEEM_TAG_PREFIX, code),
            }), 400
        if reward_type == "currency":
            if not reward_id:
                return jsonify({
                    "success": False,
                    "error": "a currency code needs reward_id (e.g. SR or RM)",
                }), 400
            if not normalised.get("amount"):
                return jsonify({
                    "success": False,
                    "error": "a currency code needs a positive amount",
                }), 400
        else:
            # Validate the id now rather than letting the grant fail later with
            # a confusing PlayFab error. Worth doing because an amount-less
            # reward_id infers "cosmetic", so a typo'd currency code lands here.
            resolved = resolve_catalog_item_id(reward_id)
            if not resolved:
                return jsonify({
                    "success": False,
                    "error": "no catalog item matches '{0}' - if this is "
                             "currency, set reward_type=currency and an "
                             "amount".format(reward_id),
                }), 400
            # Store the catalog's own spelling so listings are unambiguous.
            normalised["reward_id"] = resolved

    settings[code] = normalised
    ok, result = save_settings(settings)
    if not ok:
        return jsonify({
            "success": False,
            "error": (result or {}).get("errorMessage") or "could not save",
        }), 502

    entry = resolve_code(code)
    return jsonify({"success": True, "code": code, "entry": entry})


@app.route("/api/online-count", methods=["POST"])
def online_count_report():
    global _online_global_count, _online_global_at
    body = request.get_json(silent=True) or {}
    if not check_secret(body):
        return jsonify({"success": False, "error": "bad secret"}), 401
    try:
        count = int(body.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    _online_global_count = max(0, count)
    _online_global_at = time.time()
    return jsonify({"success": True, "online": _online_global_count})


@app.route("/api/online", methods=["GET"])
def online():
    """Public player count.

    The player list holds PlayFab IDs, so it is only returned to a caller that
    presents the secret. Previously this endpoint returned every tracked ID to
    anyone who asked.
    """
    now = time.time()
    if now - _online_global_at <= ONLINE_GLOBAL_TTL_SECONDS:
        return jsonify({"online": _online_global_count, "source": "global_count"})
    players = online_snapshot()
    if not check_secret_request():
        return jsonify({"online": len(players), "source": "tracker_fallback"})
    return jsonify({
        "online": len(players),
        "source": "tracker_fallback",
        "players": [p["playfab_id"] for p in players],
    })


@app.route("/api/dashboard", methods=["GET"])
def dashboard_data():
    """Everything the browser dashboard renders. Secret required."""
    if not check_secret_request():
        return jsonify({"success": False, "error": "bad secret"}), 401

    now = time.time()

    # Always read the per-player registry. Previously this returned players=[]
    # whenever the global count was fresh - and because the client refreshes the
    # global count every 15s against a 90s TTL, that branch was taken on nearly
    # every request, so the player list could never render.
    players = online_snapshot()
    count = len(players)
    source = "tracker_fallback"

    if now - _online_global_at <= ONLINE_GLOBAL_TTL_SECONDS:
        # The client's 15s heartbeat is the authoritative headline number; the
        # registry is detail. Prefer whichever is higher so a lagging heartbeat
        # cannot under-report.
        count = max(_online_global_count, len(players))
        source = "global_count"

    tracked = load_tracked_players()

    role_of = {}
    for key, role in (("owners", "owner"), ("admins", "admin"),
                      ("moderators", "moderator"),
                      ("content_creators", "content_creator")):
        for entry in tracked.get(key) or []:
            pid = entry if isinstance(entry, str) else (entry or {}).get("playFabId")
            name = entry.get("displayName") if isinstance(entry, dict) else None
            if pid:
                role_of[pid] = {"role": role, "display_name": name}

    rows = []
    for entry in players:
        pid = entry["playfab_id"]
        info = role_of.get(pid) or {}
        # Prefer the live display name the client just reported; fall back to the
        # roster name if this player has one.
        rows.append({
            "playfab_id": pid,
            "role": info.get("role"),
            "display_name": entry.get("name") or info.get("display_name"),
        })
    rows.sort(key=lambda r: (r["role"] is None, r["role"] or "",
                             (r["display_name"] or r["playfab_id"]).lower()))

    return jsonify({
        "success": True,
        "online": count,
        "source": source,
        "player_count": len(players),
        "players": rows,
        "tracked_counts": {
            "owners": len(tracked.get("owners") or []),
            "admins": len(tracked.get("admins") or []),
            "moderators": len(tracked.get("moderators") or []),
            "content_creators": len(tracked.get("content_creators") or []),
        },
        "playfab_configured": bool(PLAYFAB_TITLE_ID and PLAYFAB_SECRET_KEY),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })


@app.route("/api/tracker/tracked", methods=["GET"])
def tracked():
    """The role rosters. Secret required - these list named players by ID."""
    if not check_secret_request():
        return jsonify({"success": False, "error": "bad secret"}), 401
    data = load_tracked_players(force=True)
    return jsonify({
        "content_creators": data.get("content_creators") or [],
        "moderators": data.get("moderators") or [],
        "admins": data.get("admins") or [],
        "owners": data.get("owners") or [],
    })


@app.route("/api/tracker/refresh", methods=["POST"])
def refresh():
    body = request.get_json(silent=True) or {}
    if not check_secret(body):
        return jsonify({"success": False, "error": "bad secret"}), 401
    load_tracked_players(force=True)
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Meta / Info
# ---------------------------------------------------------------------------

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "SuperiorTagAlt",
        "playfab_configured": bool(PLAYFAB_TITLE_ID and PLAYFAB_SECRET_KEY),
        "api_secret_set": API_SECRET != "CHANGE_ME",
        "tracker_webhook_set": bool(TRACKER_WEBHOOK_URL),
        "vip_webhook_set": bool(TRACKER_VIP_WEBHOOK_URL),
        "report_webhook_set": bool(REPORT_WEBHOOK_URL),
    })


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "service": "SuperiorTagAlt",
        "features": ["tracker", "reports", "instaban", "dashboard"],
        "endpoints": [
            "/api/report", "/api/tracker", "/api/online-count",
            "/api/online", "/api/dashboard", "/api/tracker/tracked",
            "/api/tracker/refresh", "/api/health",
        ],
        "dashboard": "/dashboard",
    })


@app.route("/dashboard", methods=["GET"])
def dashboard_page():
    """The browser dashboard. The HTML itself is public; the data is not."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")
    if not os.path.exists(path):
        return jsonify({"success": False, "error": "dashboard.html missing"}), 500
    with open(path, "r", encoding="utf-8") as handle:
        html = handle.read()
    return Response(html, mimetype="text/html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
