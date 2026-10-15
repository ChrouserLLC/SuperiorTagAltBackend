"""
Superior Tag Alt Backend
========================

One combined Flask service providing:

  * Player tracking  (lobby join/leave, online counts, Discord embeds)
  * Player reports   (in-game report -> Discord moderation channel)
  * Insta-ban        (report can trigger a PlayFab ban via CloudScript)

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
_cooldown_lock = threading.Lock()
_online_registry = {}
_online_lock = threading.Lock()
_online_global_count = 0
_online_global_at = 0.0


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
            headers={"Content-Type": "application/json"})
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
