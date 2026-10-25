"""
Superior Tag Discord bot (HTTP interactions - no always-on process).

Discord POSTs every slash command and button click to
    /api/discord/interactions
and this module answers it directly, which is why it runs on Vercel.

Commands
    /players            live count, peaks and a chart of the last hour
    /status             PlayFab / attestation / SisterShip / data health
    /rooms              public rooms right now
    /player  (staff)    look a player up: role, ban, last login, last seen
    /ban     (staff)    ban a player for N hours (0 = permanent)
    /unban   (staff)    lift every ban on a player
    /code    (staff)    list / create / enable / disable / delete redeem codes
    /live    (staff)    keep a self-updating player-count message in a channel
Report messages posted by the bot get Ban 24h / Ban 7d / Dismiss buttons.

Data comes from the game: the Photon master client of each room calls
/api/online-count once a minute (see PlayerCountReporter.cs). With KV
(Upstash Redis) configured the history is shared by every serverless copy;
without it, each copy only sees what it received itself.

Environment
    DISCORD_APP_ID, DISCORD_PUBLIC_KEY, DISCORD_BOT_TOKEN
    DISCORD_STAFF_ROLE_IDS     comma-separated Discord role IDs allowed staff commands
    DISCORD_ADMIN_USER_IDS     optional comma-separated user IDs, always staff
    DISCORD_REPORT_CHANNEL_ID  optional: post reports here (with buttons) instead of the webhook
    DISCORD_GAME_NAME          title on embeds and the chart (default "SUPERIOR TAG")
    PUBLIC_BASE_URL            this backend's public URL (default: from the request)
    ATTESTATION_STATUS_URL, SISTERSHIP_HEALTH_URL   for /status
"""

import calendar
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

from flask import Response, jsonify, request

DISCORD_API = "https://discord.com/api/v10"

# Interaction / response types (Discord API).
PING, APP_COMMAND, COMPONENT = 1, 2, 3
R_PONG, R_MESSAGE, R_UPDATE = 1, 4, 7
EPHEMERAL = 64

def ACCENT():
    """Embed colour. Purple by default; override with DISCORD_ACCENT=#RRGGBB."""
    try:
        return int(env("DISCORD_ACCENT", "#A855F7").lstrip("#"), 16)
    except ValueError:
        return 0xA855F7


GREEN = 0x3BA55D
RED = 0xED4245
GREY = 0x4F545C

_HEX_ID = re.compile(r"^[0-9A-Fa-f]{12,32}$")

# In-process fallbacks when KV is not configured (tests, local runs).
_mem = {"counts": {}, "last": None, "rooms": {}, "seen": {}, "names": {}, "live": None, "live_at": 0.0}
_mem_lock = threading.Lock()

ROOM_TTL_SECONDS = 180
SEEN_TTL_SECONDS = 30 * 24 * 3600
COUNT_TTL_SECONDS = 26 * 3600
LIVE_UPDATE_SECONDS = 120


def env(name, default=""):
    return os.environ.get(name, default).strip()


def env_list(name):
    return [v.strip() for v in env(name).split(",") if v.strip()]


def game_name():
    return env("DISCORD_GAME_NAME", "SUPERIOR TAG")


# ---------------------------------------------------------------------------
# Signature check
# ---------------------------------------------------------------------------

def verify_signature(raw_body, signature_hex, timestamp):
    """Discord signs every interaction with Ed25519. Anything unsigned is refused."""
    public_key = env("DISCORD_PUBLIC_KEY")
    if not public_key or not signature_hex or not timestamp:
        return False
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key))
        key.verify(bytes.fromhex(signature_hex), timestamp.encode("utf-8") + raw_body)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Discord REST
# ---------------------------------------------------------------------------

def discord_api(method, path, body=None, timeout=5):
    """Calls the Discord REST API as the bot. Returns (ok, json_or_none)."""
    token = env("DISCORD_BOT_TOKEN")
    if not token:
        return False, {"message": "DISCORD_BOT_TOKEN is not set"}
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        DISCORD_API + path, data=data, method=method,
        headers={
            "Authorization": "Bot " + token,
            "Content-Type": "application/json",
            # Discord rejects requests without a bot-style User-Agent.
            "User-Agent": "DiscordBot (https://github.com/ChrouserLLC/SuperiorTagAltBackend, 1.0)",
        })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return True, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        try:
            return False, json.loads(e.read().decode("utf-8"))
        except ValueError:
            return False, {"message": "HTTP {0}".format(e.code)}
    except Exception as e:
        return False, {"message": type(e).__name__}


def http_get_json(url, timeout=2.0):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SuperiorTagAlt-Status/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "null")
        except ValueError:
            return e.code, None
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# Live data: player count history, rooms, last seen
# ---------------------------------------------------------------------------

def _minute(ts=None):
    return int((ts if ts is not None else time.time()) // 60)


def record_report(deps, reporter_id, count, room=None, players=None):
    """Stores one report from a game client (called by /api/online-count)."""
    now = time.time()
    m = _minute(now)
    if deps.kv_configured():
        deps.kv_command("SET", "pc:m:{0}".format(m), int(count), "EX", COUNT_TTL_SECONDS)
        deps.kv_command("SET", "pc:last", json.dumps({"count": int(count), "ts": now}), "EX", COUNT_TTL_SECONDS)
    else:
        with _mem_lock:
            _mem["counts"][m] = int(count)
            _mem["last"] = {"count": int(count), "ts": now}
            for k in [k for k in _mem["counts"] if k < m - 1500]:
                _mem["counts"].pop(k, None)

    if isinstance(room, dict) and room.get("code") and room.get("public"):
        code = str(room.get("code"))[:16]
        entry = {
            "code": code,
            "players": max(0, min(int(room.get("players") or 0), 64)),
            "max": max(1, min(int(room.get("max") or 10), 64)),
            "mode": str(room.get("mode") or "")[:48],
            "ts": now,
        }
        if deps.kv_configured():
            deps.kv_command("HSET", "rooms", code, json.dumps(entry))
        else:
            with _mem_lock:
                _mem["rooms"][code] = entry

    if isinstance(players, list):
        room_code = str((room or {}).get("code") or "")[:16] if isinstance(room, dict) else ""
        public = bool(isinstance(room, dict) and room.get("public"))
        for p in players[:12]:
            if not isinstance(p, dict):
                continue
            pid = str(p.get("id") or "").strip()
            name = str(p.get("name") or "").strip()[:32]
            if not _HEX_ID.match(pid):
                continue
            seen = {"ts": now, "name": name, "room": room_code if public else "-PRIVATE-",
                    "reported_by": reporter_id}
            if deps.kv_configured():
                deps.kv_command("SET", "seen:" + pid, json.dumps(seen), "EX", SEEN_TTL_SECONDS)
                if name:
                    deps.kv_command("SET", "seenname:" + name.lower(), pid, "EX", SEEN_TTL_SECONDS)
            else:
                with _mem_lock:
                    _mem["seen"][pid] = seen
                    if name:
                        _mem["names"][name.lower()] = pid

    maybe_update_live(deps)


def current_count(deps):
    """{count, ts} of the newest report, or None."""
    if deps.kv_configured():
        ok, raw = deps.kv_command("GET", "pc:last")
        if ok and raw:
            try:
                return json.loads(raw)
            except ValueError:
                return None
        return None
    with _mem_lock:
        return dict(_mem["last"]) if _mem["last"] else None


def history(deps, minutes):
    """List of (minute, count or None) for the last `minutes` minutes, oldest first."""
    now_m = _minute()
    keys = list(range(now_m - minutes + 1, now_m + 1))
    values = {}
    if deps.kv_configured():
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            ok, result = deps.kv_command("MGET", *["pc:m:{0}".format(k) for k in chunk])
            if ok and isinstance(result, list):
                for k, v in zip(chunk, result):
                    if v is not None:
                        try:
                            values[k] = int(v)
                        except (TypeError, ValueError):
                            pass
    else:
        with _mem_lock:
            values = dict(_mem["counts"])
    return [(k, values.get(k)) for k in keys]


def peak(points):
    best = None
    for m, v in points:
        if v is not None and (best is None or v >= best[1]):
            best = (m, v)
    return best


def public_rooms(deps):
    now = time.time()
    rooms = []
    if deps.kv_configured():
        ok, flat = deps.kv_command("HGETALL", "rooms")
        if ok and isinstance(flat, list):
            for i in range(0, len(flat) - 1, 2):
                try:
                    entry = json.loads(flat[i + 1])
                except (TypeError, ValueError):
                    continue
                if now - entry.get("ts", 0) > ROOM_TTL_SECONDS:
                    deps.kv_command("HDEL", "rooms", flat[i])
                else:
                    rooms.append(entry)
    else:
        with _mem_lock:
            for code, entry in list(_mem["rooms"].items()):
                if now - entry.get("ts", 0) > ROOM_TTL_SECONDS:
                    _mem["rooms"].pop(code, None)
                else:
                    rooms.append(entry)
    rooms.sort(key=lambda r: (-r.get("players", 0), r.get("code", "")))
    return rooms


def last_seen(deps, playfab_id):
    if deps.kv_configured():
        ok, raw = deps.kv_command("GET", "seen:" + playfab_id)
        if ok and raw:
            try:
                return json.loads(raw)
            except ValueError:
                return None
        return None
    with _mem_lock:
        return _mem["seen"].get(playfab_id)


def id_for_name(deps, name):
    key = (name or "").strip().lower()
    if not key:
        return None
    if deps.kv_configured():
        ok, pid = deps.kv_command("GET", "seenname:" + key)
        return pid if ok and pid else None
    with _mem_lock:
        return _mem["names"].get(key)


# ---------------------------------------------------------------------------
# Chart (PNG)
# ---------------------------------------------------------------------------

_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")


def _font(size, bold=False):
    from PIL import ImageFont
    name = "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"
    try:
        return ImageFont.truetype(os.path.join(_FONT_DIR, name), size)
    except (OSError, IOError):
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()


def _hex(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def render_chart(points, title, peak_value):
    """Player-count chart in the style of the reference: dark card, accent top
    rule, monospace labels, gradient area, a white dot on the peak and an
    accent dot on the current value. Returns PNG bytes."""
    from io import BytesIO
    from PIL import Image, ImageDraw

    S = 2  # draw at 2x and downscale for smooth lines
    W, H = 640 * S, 300 * S
    left, right, top, bottom = 58 * S, 22 * S, 78 * S, 40 * S

    bg = (30, 31, 34)
    card = (37, 38, 43)
    grid = (58, 60, 67)
    text = (232, 232, 236)
    muted = (150, 152, 160)
    accent = _hex(env("DISCORD_ACCENT", "#A855F7"))

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle([6 * S, 6 * S, W - 6 * S, H - 6 * S], fill=card)
    draw.rectangle([6 * S, 6 * S, W - 6 * S, 9 * S], fill=accent)

    f_title = _font(17 * S, bold=True)
    f_now = _font(17 * S, bold=True)
    f_small = _font(11 * S)
    f_small_b = _font(11 * S, bold=True)

    values = [v for _, v in points if v is not None]
    now_v = next((v for _, v in reversed(points) if v is not None), 0)
    top_v = max(values + [1])
    step = max(1, -(-top_v // 4))  # ceil
    if step * 4 == top_v:
        step += max(1, step // 3)  # headroom above the peak, like the reference
    y_max = step * 4

    draw.text((left, 22 * S), title.upper() + " PLAYERS", font=f_title, fill=text)
    draw.text((left, 44 * S), "LAST HOUR", font=f_small, fill=muted)
    now_label = "NOW {0}".format(now_v)
    draw.text((W - right - draw.textlength(now_label, font=f_now), 22 * S), now_label, font=f_now, fill=accent)
    peak_label = "PEAK {0}".format(peak_value if peak_value is not None else "-")
    draw.text((W - right - draw.textlength(peak_label, font=f_small_b), 44 * S), peak_label,
              font=f_small_b, fill=text)

    plot_w = W - left - right
    plot_h = H - top - bottom
    base_y = top + plot_h

    # Grid: dashed vertical lines every 10 minutes, horizontal lines per step.
    n = max(1, len(points) - 1)
    for i in range(5):
        y = int(base_y - plot_h * i / 4)
        draw.line([(left, y), (W - right, y)], fill=grid, width=S)
        label = str(step * i)
        draw.text((left - 10 * S - draw.textlength(label, font=f_small), y - 7 * S), label, font=f_small, fill=muted)
    for i, (m, _) in enumerate(points):
        if i % 10 == 0 or i == len(points) - 1:
            x = int(left + plot_w * i / n)
            for y in range(top, base_y, 8 * S):
                draw.line([(x, y), (x, min(y + 3 * S, base_y))], fill=grid, width=S)
            label = time.strftime("%H:%M", time.gmtime(m * 60))
            draw.text((x - draw.textlength(label, font=f_small) / 2, base_y + 10 * S), label,
                      font=f_small, fill=muted)

    def xy(i, v):
        return (left + plot_w * i / n, base_y - plot_h * (v / float(y_max)))

    runs, run = [], []
    for i, (_, v) in enumerate(points):
        if v is None:
            if run:
                runs.append(run)
            run = []
        else:
            run.append(xy(i, v))
    if run:
        runs.append(run)

    # Gradient area fill: accent at the line, fading out towards the baseline.
    fill_layer = Image.new("RGB", (W, H), accent)
    mask = Image.new("L", (W, H), 0)
    mdraw = ImageDraw.Draw(mask)
    for r in runs:
        if len(r) > 1:
            mdraw.polygon([(r[0][0], base_y)] + r + [(r[-1][0], base_y)], fill=255)
    fade = Image.new("L", (1, H), 0)
    for y in range(H):
        if y < top:
            a = 0
        else:
            a = int(120 - 105 * (y - top) / float(max(1, plot_h)))
        fade.putpixel((0, y), max(0, a))
    fade = fade.resize((W, H))
    from PIL import ImageChops
    mask = ImageChops.multiply(mask, fade)
    img.paste(fill_layer, (0, 0), mask)

    draw = ImageDraw.Draw(img)
    for r in runs:
        if len(r) > 1:
            draw.line(r, fill=accent, width=2 * S + 1, joint="curve")

    # White dot where the peak was first reached; accent dot on "now".
    if values:
        best = max(values)
        for i, (_, v) in enumerate(points):
            if v == best:
                px, py = xy(i, v)
                draw.ellipse([px - 4 * S, py - 4 * S, px + 4 * S, py + 4 * S], fill=(255, 255, 255))
                break
        last_i = max(i for i, (_, v) in enumerate(points) if v is not None)
        lx, ly = xy(last_i, points[last_i][1])
        draw.ellipse([lx - 5 * S, ly - 5 * S, lx + 5 * S, ly + 5 * S], fill=(255, 255, 255))
        draw.ellipse([lx - 3 * S, ly - 3 * S, lx + 3 * S, ly + 3 * S], fill=accent)
    else:
        msg = "NO DATA YET"
        draw.text(((W - draw.textlength(msg, font=f_title)) / 2, top + plot_h / 2 - 10 * S), msg,
                  font=f_title, fill=muted)

    img = img.resize((W // S, H // S), Image.LANCZOS)
    out = BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

def base_url():
    configured = env("PUBLIC_BASE_URL")
    if configured:
        return configured.rstrip("/")
    try:
        return request.host_url.rstrip("/")
    except RuntimeError:
        return ""


def players_embed(deps):
    """Matches the reference: title, one line, Current and Peak (1h), then the chart."""
    pts_hour = history(deps, 61)
    now = current_count(deps)
    p1 = peak(pts_hour)
    fresh = now is not None and time.time() - now.get("ts", 0) < 300
    count = now["count"] if fresh else 0

    return {
        "title": env("DISCORD_PLAYERS_TITLE", "how many monke"),
        "description": ("**{0}** players are online right now.".format(count) if fresh
                        else "No game client has reported in the last 5 minutes."),
        "color": ACCENT(),
        "fields": [
            {"name": "Current", "value": "**{0}**".format(count), "inline": True},
            {"name": "Peak (1h)",
             "value": ("**{0}**\n<t:{1}:R>".format(p1[1], p1[0] * 60) if p1 else "-"), "inline": True},
        ],
        "image": {"url": "{0}/api/players/chart.png?v={1}".format(base_url(), _minute())},
    }


def message(content=None, embeds=None, components=None, ephemeral=False):
    data = {"allowed_mentions": {"parse": []}}
    if content is not None:
        data["content"] = content
    if embeds is not None:
        data["embeds"] = embeds
    if components is not None:
        data["components"] = components
    if ephemeral:
        data["flags"] = EPHEMERAL
    return jsonify({"type": R_MESSAGE, "data": data})


def error_message(text):
    return message(embeds=[{"description": text, "color": RED}], ephemeral=True)


def is_staff(payload):
    member = payload.get("member") or {}
    user = member.get("user") or payload.get("user") or {}
    if user.get("id") and user.get("id") in env_list("DISCORD_ADMIN_USER_IDS"):
        return True
    roles = set(member.get("roles") or [])
    return bool(roles & set(env_list("DISCORD_STAFF_ROLE_IDS")))


def actor_name(payload):
    member = payload.get("member") or {}
    user = member.get("user") or payload.get("user") or {}
    return member.get("nick") or user.get("global_name") or user.get("username") or "staff"


def options_of(data):
    """Flattens slash-command options. Returns (subcommand or None, {name: value})."""
    opts = data.get("options") or []
    sub = None
    if opts and opts[0].get("type") in (1, 2):
        sub = opts[0].get("name")
        opts = opts[0].get("options") or []
    return sub, {o.get("name"): o.get("value") for o in opts}


# ---------------------------------------------------------------------------
# Player helpers
# ---------------------------------------------------------------------------

def resolve_player(deps, query):
    """PlayFab ID from an ID, a recently-seen in-game name, or a PlayFab display name."""
    q = (query or "").strip()
    if not q:
        return None
    if _HEX_ID.match(q):
        return q.upper()
    pid = id_for_name(deps, q)
    if pid:
        return pid
    ok, result = deps.pf_admin_request("GetUserAccountInfo", {"TitleDisplayName": q})
    if ok:
        pid = ((result.get("data") or {}).get("UserInfo") or {}).get("PlayFabId")
        if pid:
            return pid
    return None


def _parallel(funcs):
    """Runs zero-arg callables in parallel, returns their results in order."""
    results = [None] * len(funcs)

    def run(i, f):
        try:
            results[i] = f()
        except Exception as e:  # pragma: no cover - defensive
            results[i] = e

    threads = [threading.Thread(target=run, args=(i, f)) for i, f in enumerate(funcs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(4.0)
    return results


def _iso_to_ts(value):
    try:
        return calendar.timegm(time.strptime(str(value)[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return None


def ban_player(deps, playfab_id, hours, reason):
    ban = {"PlayFabId": playfab_id, "Reason": reason[:140]}
    if hours and hours > 0:
        ban["DurationInHours"] = int(hours)
    ok, result = deps.pf_request("BanUsers", {"Bans": [ban]})
    return ok, (result or {}).get("errorMessage")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_players(deps, payload, opts):
    return message(embeds=[players_embed(deps)])


def cmd_status(deps, payload, opts):
    att_url = env("ATTESTATION_STATUS_URL", "https://superiortagattestation.vercel.app/api/status")
    ss_url = env("SISTERSHIP_HEALTH_URL", "https://sistership.onrender.com/api/v1/health")

    pf, att, ss = _parallel([
        lambda: deps.pf_request("GetTitleData", {"Keys": ["Version"]}),
        lambda: http_get_json(att_url),
        lambda: http_get_json(ss_url),
    ])

    lines = []
    if isinstance(pf, tuple) and pf[0]:
        version = ((pf[1].get("data") or {}).get("Data") or {}).get("Version") or "-"
        lines.append("**PlayFab** - up (required version `{0}`)".format(version))
    else:
        lines.append("**PlayFab** - DOWN or not configured")

    if isinstance(att, tuple) and att[0] is not None:
        state = (att[1] or {}).get("status") if isinstance(att[1], dict) else None
        lines.append("**Attestation** - {0}".format((state or "HTTP {0}".format(att[0])).lower()))
    else:
        lines.append("**Attestation** - unreachable")

    if isinstance(ss, tuple) and ss[0] == 200 and isinstance(ss[1], dict) and ss[1].get("success"):
        lines.append("**SisterShip** - up ({0} sessions)".format(ss[1].get("sessions", "?")))
    elif isinstance(ss, tuple) and ss[0] is not None:
        lines.append("**SisterShip** - error (HTTP {0})".format(ss[0]))
    else:
        lines.append("**SisterShip** - asleep or unreachable (Render free tier sleeps when idle)")

    now = current_count(deps)
    if now:
        age = int(time.time() - now.get("ts", 0))
        lines.append("**Player data** - last report {0}s ago".format(age) if age < 300
                     else "**Player data** - stale (last report <t:{0}:R>)".format(int(now["ts"])))
    else:
        lines.append("**Player data** - no reports yet")
    lines.append("**Shared storage (KV)** - {0}".format("on" if deps.kv_configured() else
                                                       "OFF: history and locks are per server copy"))
    ok_all = all(("DOWN" not in l and "unreachable" not in l and "error" not in l) for l in lines[:3])
    return message(embeds=[{"title": game_name() + " status", "description": "\n".join(lines),
                            "color": GREEN if ok_all else RED}])


def cmd_rooms(deps, payload, opts):
    rooms = public_rooms(deps)
    if not rooms:
        return message(embeds=[{"title": "Public rooms", "description": "No public rooms reported right now.",
                                "color": GREY}])
    lines = []
    for r in rooms[:20]:
        mode = deps.format_game_mode(r.get("mode") or "") if r.get("mode") else "-"
        lines.append("`{0}` - {1}/{2} - {3}".format(r["code"], r["players"], r["max"], mode))
    total = sum(r.get("players", 0) for r in rooms)
    return message(embeds=[{
        "title": "Public rooms ({0})".format(len(rooms)),
        "description": "\n".join(lines),
        "color": ACCENT(),
        "footer": {"text": "{0} players in public rooms".format(total)},
    }])


def cmd_player(deps, payload, opts):
    query = opts.get("player") or ""
    pid = resolve_player(deps, query)
    if not pid:
        return error_message("No player found for `{0}`. Use their PlayFab ID, or the name they used "
                             "in a room recently.".format(query[:40]))

    info, ban, role, seen = _parallel([
        lambda: deps.pf_request("GetUserAccountInfo", {"PlayFabId": pid}),
        lambda: deps.active_ban(pid),
        lambda: deps.lookup_role(pid),
        lambda: last_seen(deps, pid),
    ])

    fields = [{"name": "PlayFab ID", "value": "`{0}`".format(pid), "inline": True},
              {"name": "Role", "value": (role or "player").replace("_", " "), "inline": True}]
    title = query
    if isinstance(info, tuple) and info[0]:
        user = (info[1].get("data") or {}).get("UserInfo") or {}
        tinfo = user.get("TitleInfo") or {}
        title = tinfo.get("DisplayName") or title
        created = _iso_to_ts(tinfo.get("Created") or user.get("Created"))
        last_login = _iso_to_ts(tinfo.get("LastLogin"))
        if created:
            fields.append({"name": "Created", "value": "<t:{0}:D>".format(created), "inline": True})
        if last_login:
            fields.append({"name": "Last login", "value": "<t:{0}:R>".format(last_login), "inline": True})
    else:
        fields.append({"name": "Account", "value": "PlayFab lookup failed", "inline": True})

    if isinstance(ban, dict) and ban.get("error"):
        fields.append({"name": "Ban", "value": "could not check", "inline": False})
    elif ban:
        length = "permanent" if ban.get("permanent") else "{0}h left".format(ban.get("hours"))
        fields.append({"name": "Ban", "value": "**BANNED** ({0})\n{1}".format(length, ban.get("reason") or "-"),
                       "inline": False})
    else:
        fields.append({"name": "Ban", "value": "not banned", "inline": False})

    if isinstance(seen, dict):
        fields.append({"name": "Last seen in a room",
                       "value": "<t:{0}:R> as `{1}` in `{2}`".format(int(seen.get("ts", 0)), seen.get("name") or "?",
                                                                    seen.get("room") or "?"),
                       "inline": False})

    return message(embeds=[{"title": title, "color": RED if ban and not (isinstance(ban, dict) and ban.get("error"))
                            else ACCENT(), "fields": fields}], ephemeral=True)


def cmd_ban(deps, payload, opts):
    pid = resolve_player(deps, opts.get("player"))
    if not pid:
        return error_message("No player found for that name or ID.")
    if deps.lookup_role(pid) in ("owner", "admin", "moderator"):
        return error_message("That player is staff. Remove their role first if you really mean it.")
    hours = int(opts.get("hours") or 0)
    if hours < 0 or hours > 24 * 365:
        return error_message("hours must be between 0 (permanent) and 8760.")
    reason = "[Discord] {0}: {1}".format(actor_name(payload), (opts.get("reason") or "no reason given")[:100])
    ok, err = ban_player(deps, pid, hours, reason)
    if not ok:
        return error_message("PlayFab refused the ban: {0}".format(err or "unknown error"))
    length = "permanently" if hours == 0 else "for {0}h".format(hours)
    return message(embeds=[{
        "description": "Banned `{0}` {1}.\nReason: {2}\nTakes effect the next time they log in.".format(
            pid, length, reason),
        "color": RED}], ephemeral=True)


def cmd_unban(deps, payload, opts):
    pid = resolve_player(deps, opts.get("player"))
    if not pid:
        return error_message("No player found for that name or ID.")
    ok, result = deps.pf_request("RevokeAllBansForUser", {"PlayFabId": pid})
    if not ok:
        return error_message("PlayFab refused: {0}".format((result or {}).get("errorMessage") or "unknown error"))
    return message(embeds=[{"description": "Lifted every ban on `{0}`.".format(pid), "color": GREEN}],
                   ephemeral=True)


def _code_line(code, e):
    state = "on" if e.get("enabled", True) else "OFF"
    if e.get("reward_type") == "currency":
        reward = "{0} {1}".format(e.get("amount", 0), e.get("reward_id", ""))
    else:
        reward = e.get("reward_label") or e.get("reward_id") or "?"
    uses = e.get("max_uses") or 1
    return "`{0}` [{1}] {2} - {3} use(s) per player".format(code, state, reward, uses)


def cmd_code(deps, payload, sub, opts):
    if sub == "list":
        codes, problems = deps.list_codes()
        if not codes:
            return message(embeds=[{"description": "No redeem codes yet.", "color": GREY}], ephemeral=True)
        lines = [_code_line(c, codes[c]) for c in sorted(codes)][:40]
        text = "\n".join(lines)
        if problems:
            text += "\n\n**Catalog problems:**\n" + "\n".join("- " + str(p) for p in problems[:5])
        return message(embeds=[{"title": "Redeem codes ({0})".format(len(codes)), "description": text[:4000],
                                "color": ACCENT()}], ephemeral=True)

    code = str(opts.get("code") or "").strip().upper()
    if not code:
        return error_message("A code is required.")

    if sub == "create":
        body = {"code": code, "enabled": True}
        kind = (opts.get("type") or "currency").lower()
        reward = str(opts.get("reward") or "").strip()
        if kind == "currency":
            body.update({"reward_type": "currency", "reward_id": reward.upper() or "SR",
                         "amount": int(opts.get("amount") or 0)})
            body["reward_label"] = "{0} {1}".format(body["amount"], body["reward_id"])
        else:
            if reward:
                body.update({"reward_type": "cosmetic", "reward_id": reward})
        if opts.get("max_uses") is not None:
            body["max_uses"] = int(opts.get("max_uses"))
        if opts.get("note"):
            body["note"] = str(opts.get("note"))[:100]
    elif sub in ("enable", "disable"):
        body = {"code": code, "enabled": sub == "enable"}
    elif sub == "delete":
        body = {"code": code, "delete": True}
    else:
        return error_message("Unknown subcommand.")

    result, status = deps.upsert_code(body)
    if status != 200 or not result.get("success"):
        return error_message("Could not {0} `{1}`: {2}".format(sub, code, result.get("error") or status))
    if sub == "delete":
        return message(embeds=[{"description": "Deleted the settings for `{0}`.".format(code), "color": GREEN}],
                       ephemeral=True)
    entry = result.get("entry") or {}
    return message(embeds=[{"description": "Saved: " + _code_line(code, entry), "color": GREEN}], ephemeral=True)


def cmd_live(deps, payload, sub, opts):
    if not env("DISCORD_BOT_TOKEN"):
        return error_message("DISCORD_BOT_TOKEN is not set on the backend.")
    if sub == "stop":
        target = load_live(deps)
        save_live(deps, None)
        if target:
            discord_api("DELETE", "/channels/{0}/messages/{1}".format(target["channel_id"], target["message_id"]))
        return message(embeds=[{"description": "Live player count stopped.", "color": GREY}], ephemeral=True)

    channel_id = str(opts.get("channel") or payload.get("channel_id") or "")
    ok, msg = discord_api("POST", "/channels/{0}/messages".format(channel_id),
                          {"embeds": [players_embed(deps)], "allowed_mentions": {"parse": []}})
    if not ok or not msg or not msg.get("id"):
        return error_message("Could not post in <#{0}>: {1}. Give the bot Send Messages and Embed Links "
                             "there.".format(channel_id, (msg or {}).get("message", "error")))
    save_live(deps, {"channel_id": channel_id, "message_id": msg["id"]})
    return message(embeds=[{"description": "Live player count posted in <#{0}>. It updates every couple of "
                                           "minutes while players are online.".format(channel_id),
                            "color": GREEN}], ephemeral=True)


def load_live(deps):
    if deps.kv_configured():
        ok, raw = deps.kv_command("GET", "live:target")
        if ok and raw:
            try:
                return json.loads(raw)
            except ValueError:
                return None
        return None
    with _mem_lock:
        return _mem["live"]


def save_live(deps, target):
    if deps.kv_configured():
        if target:
            deps.kv_command("SET", "live:target", json.dumps(target))
        else:
            deps.kv_command("DEL", "live:target")
    else:
        with _mem_lock:
            _mem["live"] = target


def maybe_update_live(deps):
    """Edits the /live message at most every LIVE_UPDATE_SECONDS, driven by game reports."""
    if not env("DISCORD_BOT_TOKEN"):
        return
    target = load_live(deps)
    if not target:
        return
    now = time.time()
    if deps.kv_configured():
        ok, last = deps.kv_command("GET", "live:at")
        try:
            last = float(last) if ok and last else 0.0
        except (TypeError, ValueError):
            last = 0.0
    else:
        last = _mem["live_at"]
    if now - last < LIVE_UPDATE_SECONDS:
        return
    release = deps.acquire_lock("live-update", 60)
    if release is None:
        return
    try:
        if deps.kv_configured():
            deps.kv_command("SET", "live:at", str(now))
        else:
            _mem["live_at"] = now
        ok, resp = discord_api("PATCH", "/channels/{0}/messages/{1}".format(target["channel_id"], target["message_id"]),
                               {"embeds": [players_embed(deps)]}, timeout=3)
        if not ok and isinstance(resp, dict) and resp.get("code") == 10008:
            save_live(deps, None)  # message was deleted in Discord
    finally:
        release()


# ---------------------------------------------------------------------------
# Reports with moderation buttons
# ---------------------------------------------------------------------------

def report_buttons(reported_id):
    if not reported_id or not _HEX_ID.match(reported_id):
        return []
    return [{"type": 1, "components": [
        {"type": 2, "style": 4, "label": "Ban 24h", "custom_id": "rban:24:" + reported_id},
        {"type": 2, "style": 4, "label": "Ban 7d", "custom_id": "rban:168:" + reported_id},
        {"type": 2, "style": 2, "label": "Dismiss", "custom_id": "rdis:" + reported_id},
    ]}]


def post_report(webhook_payload, reported_id, fallback):
    """Posts a report embed through the bot (with buttons) when configured.

    Returns (sent, error). Falls back to `fallback(payload)` (the webhook) when
    the bot or channel is not configured or the bot post fails.
    """
    channel = env("DISCORD_REPORT_CHANNEL_ID")
    if channel and env("DISCORD_BOT_TOKEN"):
        body = dict(webhook_payload)
        body["components"] = report_buttons(reported_id)
        body["allowed_mentions"] = {"parse": []}
        body.pop("username", None)
        body.pop("avatar_url", None)
        ok, resp = discord_api("POST", "/channels/{0}/messages".format(channel), body, timeout=4)
        if ok:
            return True, None
    return fallback(webhook_payload)


def handle_component(deps, payload):
    data = payload.get("data") or {}
    custom_id = str(data.get("custom_id") or "")
    if not is_staff(payload):
        return error_message("Only staff can use these buttons.")

    original = (payload.get("message") or {}).get("embeds") or []
    embed = dict(original[0]) if original else {"description": "Report"}
    who = actor_name(payload)

    if custom_id.startswith("rban:"):
        _, hours, pid = custom_id.split(":", 2)
        hours = int(hours)
        if deps.lookup_role(pid) in ("owner", "admin", "moderator"):
            return error_message("That player is staff - not banned.")
        ok, err = ban_player(deps, pid, hours, "[Report] banned by {0} via Discord".format(who))
        if not ok:
            return error_message("PlayFab refused the ban: {0}".format(err or "unknown error"))
        outcome = "Banned {0}h by {1}".format(hours, who)
        embed["color"] = RED
    elif custom_id.startswith("rdis:"):
        outcome = "Dismissed by {0}".format(who)
        embed["color"] = GREY
    else:
        return error_message("Unknown button.")

    embed["footer"] = {"text": outcome}
    return jsonify({"type": R_UPDATE, "data": {"embeds": [embed], "components": [],
                                                "allowed_mentions": {"parse": []}}})


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

STAFF_COMMANDS = {"player", "ban", "unban", "code", "live"}


def register(app, deps):
    @app.route("/api/discord/interactions", methods=["POST"])
    def discord_interactions():
        raw = request.get_data(cache=True)
        if not verify_signature(raw, request.headers.get("X-Signature-Ed25519", ""),
                                request.headers.get("X-Signature-Timestamp", "")):
            return "invalid request signature", 401
        try:
            payload = json.loads(raw.decode("utf-8"))
        except ValueError:
            return "bad json", 400

        kind = payload.get("type")
        if kind == PING:
            return jsonify({"type": R_PONG})
        if kind == COMPONENT:
            return handle_component(deps, payload)
        if kind != APP_COMMAND:
            return error_message("Unsupported interaction.")

        data = payload.get("data") or {}
        name = data.get("name")
        sub, opts = options_of(data)
        if name in STAFF_COMMANDS and not is_staff(payload):
            return error_message("That command is for staff.")

        if name == "players":
            return cmd_players(deps, payload, opts)
        if name == "status":
            return cmd_status(deps, payload, opts)
        if name == "rooms":
            return cmd_rooms(deps, payload, opts)
        if name == "player":
            return cmd_player(deps, payload, opts)
        if name == "ban":
            return cmd_ban(deps, payload, opts)
        if name == "unban":
            return cmd_unban(deps, payload, opts)
        if name == "code":
            return cmd_code(deps, payload, sub, opts)
        if name == "live":
            return cmd_live(deps, payload, sub, opts)
        return error_message("Unknown command.")

    @app.route("/api/players/chart.png", methods=["GET"])
    def players_chart():
        pts = history(deps, 61)
        p = peak(pts)
        png = render_chart(pts, game_name(), p[1] if p else None)
        return Response(png, mimetype="image/png", headers={"Cache-Control": "public, max-age=60"})


# ---------------------------------------------------------------------------
# Slash command definitions (used by tools/register_discord_commands.py)
# ---------------------------------------------------------------------------

def command_definitions():
    STR, INT, CHANNEL, SUB = 3, 4, 7, 1
    staff = "0"  # hidden from everyone but admins by default; grant to your staff role in Server Settings

    def opt(name, desc, kind=STR, required=True, **extra):
        o = {"type": kind, "name": name, "description": desc, "required": required}
        o.update(extra)
        return o

    return [
        {"name": "players", "description": "How many players are online, with a chart of the last hour"},
        {"name": "status", "description": "Is PlayFab, attestation and SisterShip up?"},
        {"name": "rooms", "description": "Public rooms right now"},
        {"name": "player", "description": "Look a player up (staff)", "default_member_permissions": staff,
         "options": [opt("player", "PlayFab ID or the in-game name")]},
        {"name": "ban", "description": "Ban a player (staff)", "default_member_permissions": staff,
         "options": [opt("player", "PlayFab ID or the in-game name"),
                     opt("hours", "Hours; 0 = permanent", INT, min_value=0, max_value=8760),
                     opt("reason", "Why", STR)]},
        {"name": "unban", "description": "Lift every ban on a player (staff)", "default_member_permissions": staff,
         "options": [opt("player", "PlayFab ID or the in-game name")]},
        {"name": "code", "description": "Manage redeem codes (staff)", "default_member_permissions": staff,
         "options": [
             {"type": SUB, "name": "list", "description": "List every code"},
             {"type": SUB, "name": "create", "description": "Create or update a code",
              "options": [opt("code", "The code players type"),
                          opt("type", "What it gives", choices=[{"name": "currency", "value": "currency"},
                                                                {"name": "cosmetic", "value": "cosmetic"}]),
                          opt("reward", "Currency code (SR, RM) or catalog item ID", required=False),
                          opt("amount", "Currency amount", INT, required=False, min_value=1),
                          opt("max_uses", "Uses per player (default 1)", INT, required=False, min_value=1),
                          opt("note", "Note for staff", required=False)]},
             {"type": SUB, "name": "enable", "description": "Turn a code on", "options": [opt("code", "The code")]},
             {"type": SUB, "name": "disable", "description": "Turn a code off", "options": [opt("code", "The code")]},
             {"type": SUB, "name": "delete", "description": "Delete a code's settings",
              "options": [opt("code", "The code")]},
         ]},
        {"name": "live", "description": "Self-updating player count message (staff)",
         "default_member_permissions": staff,
         "options": [
             {"type": SUB, "name": "start", "description": "Post it in a channel",
              "options": [opt("channel", "Where", CHANNEL)]},
             {"type": SUB, "name": "stop", "description": "Stop and delete it"},
         ]},
    ]
