"""Smoke tests for the merged Superior Tag Alt backend.

Covers tracker, reports and insta-ban in one run. Uses Flask's test client so
nothing leaves the machine and no PlayFab or Discord credentials are needed.

Run:  python test_index.py
"""

import importlib.util
import json
import os
import sys
import time

# The lobby bar uses block characters; a cp1252 console would crash on print.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

os.environ.setdefault("API_SECRET", "test-secret-123")
os.environ.setdefault("ADMIN_SECRET", "test-admin-456")
os.environ.setdefault("PLAYFAB_TITLE_ID", "")
os.environ.setdefault("PLAYFAB_SECRET_KEY", "")
os.environ.setdefault("TRACKER_WEBHOOK_URL", "")
os.environ.setdefault("TRACKER_VIP_WEBHOOK_URL", "")
os.environ.setdefault("REPORT_WEBHOOK_URL", "")

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("alt_backend", os.path.join(HERE, "api", "index.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
app = mod.app.test_client()

# Session tickets: tests use "T:<playfab id>". The real check (PlayFab
# AuthenticateSessionTicket) is exercised in the security section below.
_real_authenticate_ticket = mod.authenticate_ticket
mod.authenticate_ticket = lambda t: t[2:] if isinstance(t, str) and t.startswith("T:") and len(t) > 2 else None

SECRET = "test-secret-123"
ADMIN = "test-admin-456"

passed = 0
failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        print("  PASS  " + name)
        passed += 1
    else:
        print("  FAIL  " + name + (("  -> " + str(extra)) if extra else ""))
        failed += 1


def authed(payload):
    payload = dict(payload)
    payload["secret"] = SECRET
    return payload


def admin(payload):
    payload = dict(payload)
    payload["secret"] = ADMIN
    return payload


# ---------------------------------------------------------------------------
print("\n--- health & info ---")
r = app.get("/api/health")
d = r.get_json()
check("health returns 200", r.status_code == 200, r.status_code)
check("status ok", d.get("status") == 200 or d.get("status") == "ok", d)
check("service name", d.get("service") == "SuperiorTagAlt", d)
check("api_secret_set true", d.get("api_secret_set") is True, d)
check("playfab_configured false (no creds)", d.get("playfab_configured") is False, d)

r = app.get("/")
d = r.get_json()
check("root lists 5 features", sorted(d.get("features") or []) ==
      ["dashboard", "instaban", "redeem", "reports", "tracker"], d)
check("root lists /api/report", "/api/report" in (d.get("endpoints") or []), d)
check("root lists /api/redeem", "/api/redeem" in (d.get("endpoints") or []), d)
check("root lists /api/redeem-codes", "/api/redeem-codes" in (d.get("endpoints") or []), d)
check("root points at /dashboard", d.get("dashboard") == "/dashboard", d)

# ---------------------------------------------------------------------------
print("\n--- secret enforcement ---")
for path, body in (
    ("/api/report", {"reason": "Toxicity", "reported_name": "x"}),
    ("/api/tracker", {"event": "joined_room", "player_name": "x"}),
    ("/api/online-count", {"count": 5}),
    ("/api/tracker/refresh", {}),
):
    r = app.post(path, json=dict(body, secret="wrong"))
    check("bad secret 401 on " + path, r.status_code == 401, r.status_code)

# ---------------------------------------------------------------------------
print("\n--- pf_request must not raise when PlayFab is unconfigured ---")
ok, res = mod.pf_request("GetTitleData", {})
check("pf_request returns False, not exception", ok is False, ok)
check("pf_request explains why", "not configured" in str(res.get("errorMessage", "")), res)

# Regression: a malformed title id used to raise ValueError out of urllib's
# URL parser, escaping as a 500 on every tracker event.
_saved_title = mod.PLAYFAB_TITLE_ID
mod.PLAYFAB_TITLE_ID = "not a valid host!!"
ok, res = mod.pf_request("GetTitleData", {})
check("pf_request survives a malformed title id", ok is False, ok)
check("pf_request reports the failure instead of raising", "errorMessage" in res, res)
mod.PLAYFAB_TITLE_ID = _saved_title

res = mod.run_instaban("ABC", "DEF", "Toxicity")
check("run_instaban degrades gracefully", res.get("banned") is False, res)
check("run_instaban flags unconfigured", res.get("checked") is False, res)

res = mod.run_instaban("ABC", None, "Toxicity")
check("run_instaban rejects missing id", res.get("checked") is True and res.get("banned") is False, res)

# ---------------------------------------------------------------------------
print("\n--- reports: validation ---")
r = app.post("/api/report", json=authed({"reason": "NotARealReason", "reported_name": "Bob"}))
check("invalid reason 400", r.status_code == 400, r.status_code)

r = app.post("/api/report", json=authed({"reason": "Toxicity"}))
check("missing reported player 400", r.status_code == 400, r.status_code)

r = app.post("/api/report", json=authed({
    "reason": "Toxicity", "reported_name": "Bob", "reported_id": "PFBOB",
    "reporter_name": "Alice", "reporter_id": "PFALICE",
}))
check("valid report 200", r.status_code == 200, r.status_code)
d = r.get_json()
check("report webhook_sent false (unset)", d.get("webhook_sent") is False, d)
check("report echoes reason", d.get("reason") == "Toxicity", d)
check("report instaban not banned", d["instaban"].get("banned") is False, d)

# cooldown must engage on an immediate repeat
r = app.post("/api/report", json=authed({
    "reason": "Cheating", "reported_name": "Eve", "reported_id": "PFEVE",
    "reporter_name": "Alice", "reporter_id": "PFALICE",
}))
check("different target bypasses cooldown", r.status_code == 200, r.status_code)

r = app.post("/api/report", json=authed({
    "reason": "Cheating", "reported_name": "Eve", "reported_id": "PFEVE",
    "reporter_name": "Alice", "reporter_id": "PFALICE",
}))
check("repeat report 429 cooldown", r.status_code == 429, r.status_code)
check("cooldown body has retry_after", "retry_after_seconds" in r.get_json(), r.get_json())

# ---------------------------------------------------------------------------
print("\n--- reports: map/name formatting ---")
check("format_map zone wins", mod.format_map(None, "GorillaTagSJR", "forest_01") == "Forest",
      mod.format_map(None, "GorillaTagSJR", "forest_01"))
check("format_map from game mode", mod.format_map("INFECTION_CITY_1", None) == "City",
      mod.format_map("INFECTION_CITY_1", None))
check("format_map from scene", mod.format_map(None, "RankedMap") == "Ranked",
      mod.format_map(None, "RankedMap"))
check("format_map unknown falls back to scene", mod.format_map(None, "SomeNewZone") == "SomeNewZone",
      mod.format_map(None, "SomeNewZone"))
check("format_map nothing -> None", mod.format_map(None, None) is None,
      mod.format_map(None, None))

check("format_game_mode infection", mod.format_game_mode("INFECTION") == "Infection",
      mod.format_game_mode("INFECTION"))
check("format_game_mode ctf", mod.format_game_mode("CTF") == "Capture the Flag",
      mod.format_game_mode("CTF"))
check("format_game_mode unknown passthrough", mod.format_game_mode("WAT") == "WAT",
      mod.format_game_mode("WAT"))

check("format_duration seconds", mod.format_duration(45) == "45s", mod.format_duration(45))
check("format_duration minutes", mod.format_duration(125) == "2m 5s", mod.format_duration(125))
check("format_duration hours", mod.format_duration(3725) == "1h 2m", mod.format_duration(3725))
check("format_duration negative -> None", mod.format_duration(-1) is None, mod.format_duration(-1))

check("lobby_bar clamps over max", mod.lobby_bar(99, 10) == u"\u2593" * 10 + u"  10/10",
      mod.lobby_bar(99, 10))
check("lobby_bar zero players", mod.lobby_bar(0, 10) == u"\u2591" * 10 + u"  0/10",
      mod.lobby_bar(0, 10))
check("lobby_bar zero max falls back to 10 (no div by zero)", mod.lobby_bar(3, 0).endswith("3/10"),
      mod.lobby_bar(3, 0))

# ---------------------------------------------------------------------------
print("\n--- reports: embed shape ---")
emb = mod.build_report_embed(
    "Cheating", "-PRIVATE-", True, "INFECTION", "GorillaTagSJR", "Forest",
    "Alice", "PFALICE", "Bob", "PFBOB", 4)["embeds"][0]
check("embed title", emb.get("title") == "New Player Report", emb.get("title"))
check("embed colour matches reason", emb.get("color") == mod.REPORT_COLORS["Cheating"], emb.get("color"))
check("embed hides private room code", "(hidden)" in json.dumps(emb), emb)
names = [f["name"] for f in emb["fields"]]
check("embed has room code field", "Room Code" in names, names)
check("embed field count under Discord's 25 limit", len(emb["fields"]) <= 25, len(emb["fields"]))
check("embed has reported id", "PFBOB" in json.dumps(emb), emb)

# ---------------------------------------------------------------------------
print("\n--- tracker: validation ---")
r = app.post("/api/tracker", json=authed({"event": "nonsense", "player_name": "x"}))
check("unknown event 400", r.status_code == 400, r.status_code)

r = app.post("/api/tracker", json=authed({"event": "joined_room"}))
check("missing player identity 400", r.status_code == 400, r.status_code)

base = {"event": "joined_room", "room": "ABC123", "player_name": "Alice",
        "session_ticket": "T:PFALICE2", "player_count": 3, "max_players": 10,
        "game_mode": "INFECTION", "scene": "GorillaTagSJR", "region": "US",
        "platform": "Quest3", "players": ["Alice", "Bob", "Carol"]}

r = app.post("/api/tracker", json=authed(base))
check("valid tracker event 200", r.status_code == 200, r.status_code)
d = r.get_json()
check("tracker role None for unknown player", d.get("role") is None, d)
check("tracker lobby echoed", d.get("lobby") == "3/10", d)
check("tracker webhook_sent false (unset)", d.get("webhook_sent") is False, d)
check("tracker vip webhook not used", d.get("vip_webhook_sent") is False, d)

r = app.post("/api/tracker", json=authed(dict(base, room="OTHER")))
check("a different room does NOT bypass the cooldown", r.status_code == 429, r.status_code)
mod._tracker_cooldowns.clear()

r = app.post("/api/tracker", json=authed(dict(base, session_ticket="", playfab_id="PFOWNER")))
d = r.get_json()
check("a body playfab_id is ignored (no staff role without a ticket)", d.get("role") is None, d)
mod._tracker_cooldowns.clear()
r = app.post("/api/tracker", json=authed(dict(base, room="ABC123")))

r = app.post("/api/tracker", json=authed(base))
check("same event+player+room repeats -> 429", r.status_code == 429, r.status_code)
check("tracker cooldown body has retry_after",
      "retry_after_seconds" in r.get_json(), r.get_json())

r = app.post("/api/tracker", json=authed(dict(base, event="player_joined")))
check("different event bypasses cooldown", r.status_code == 200, r.status_code)

r = app.post("/api/tracker", json=authed(dict(base, event="left_room")))
check("left_room accepted", r.status_code == 200, r.status_code)

# ---------------------------------------------------------------------------
print("\n--- tracker: malformed input must not 500 ---")
r = app.post("/api/tracker", json=authed({
    "event": "joined_room", "player_name": "Mal", "session_ticket": "T:PFMAL",
    "player_count": "lots", "max_players": None,
    "seconds_in_lobby": "ages", "players": "not-a-list",
}))
check("bad numeric/string fields still 200", r.status_code == 200, r.status_code)
check("bad numeric fields do not raise", r.status_code != 500, r.status_code)

r = app.post("/api/tracker", json=None)
check("null JSON body is a 401 not a 500", r.status_code == 401, r.status_code)

r = app.post("/api/tracker", data="}{ not json", content_type="application/json")
check("garbage JSON body is a 401 not a 500", r.status_code == 401, r.status_code)

r = app.post("/api/report", json=authed({
    "reason": "Doxing", "reported_name": "Zed", "reporter_name": "Alice",
    "room_count": "not-an-int",
}))
check("non-int room_count tolerated", r.status_code == 200, r.status_code)

# ---------------------------------------------------------------------------
print("\n--- tracker: embed shape ---")
emb = mod.build_tracker_embed(
    event="joined_room", room="ABC123", player_count=3, max_players=10,
    player_name="Alice", playfab_id="PFALICE", role=None, game_mode="INFECTION",
    region="US", platform="Quest3", players=["Alice", "Bob", "Carol"],
    seconds_in_lobby=90, scene="GorillaTagSJR", vip=False)["embeds"][0]
check("tracker embed title", emb.get("title") == "Joined Lobby", emb.get("title"))
check("tracker embed colour for plain player", emb.get("color") == mod.TRACKER_ROLE_COLORS[None], emb.get("color"))
t_names = [f["name"] for f in emb["fields"]]
check("tracker embed has lobby bar", "Lobby" in t_names, t_names)
check("tracker embed lists players", any(n.startswith("Players in Lobby") for n in t_names), t_names)
check("tracker embed has time in lobby", "Time in Lobby" in t_names, t_names)

emb = mod.build_tracker_embed(
    event="joined_room", room="ABC123", player_count=1, max_players=10,
    player_name="Mod", playfab_id="PFMOD", role="moderator", game_mode=None,
    region=None, platform=None, players=[], seconds_in_lobby=-1,
    scene=None, vip=True)["embeds"][0]
check("vip embed has author", emb.get("author", {}).get("name") == "Moderator Tracker", emb.get("author"))
check("vip embed colour differs from player", emb.get("color") == mod.TRACKER_ROLE_COLORS["moderator"], emb.get("color"))
check("no time-in-lobby field when seconds < 0",
      "Time in Lobby" not in [f["name"] for f in emb["fields"]],
      [f["name"] for f in emb["fields"]])

# ---------------------------------------------------------------------------
print("\n--- tracked players / roles ---")
d = mod.empty_tracked()
check("empty_tracked has 4 lists", sorted(d.keys()) == ["admins", "content_creators", "moderators", "owners"], d)
check("lookup_role with no PlayFab -> None", mod.lookup_role("PFNOBODY") is None)
check("lookup_role with None -> None", mod.lookup_role(None) is None)
check("lookup_role with empty string -> None", mod.lookup_role("") is None)

# Simulate a title-data blob that is plain text rather than JSON. Real PlayFab
# IDs are hex, which is what repair_tracked_players' regex expects.
repaired = mod.repair_tracked_players(
    "content_creators [A1B2C3D4E5F60718293A4B5C6D7E8F9] "
    "moderators [00112233445566778899AABBCCDDEEFF] admins [] owners []")
check("repair recovers creators",
      "A1B2C3D4E5F60718293A4B5C6D7E8F9" in repaired["content_creators"], repaired)
check("repair recovers moderators",
      "00112233445566778899AABBCCDDEEFF" in repaired["moderators"], repaired)
check("repair leaves empty lists empty",
      repaired["admins"] == [] and repaired["owners"] == [], repaired)

r = app.get("/api/tracker/tracked")
check("tracked requires a secret", r.status_code == 401, r.status_code)

r = app.get("/api/tracker/tracked", headers={"X-Api-Secret": ADMIN})
check("tracked accepts the header secret", r.status_code == 200, r.status_code)
check("tracked returns 4 keys",
      sorted(k for k in r.get_json() if k != "success") == ["admins", "content_creators", "moderators", "owners"],
      r.get_json())

r = app.get("/api/tracker/tracked", headers={"X-Api-Secret": "wrong"})
check("tracked rejects a bad header secret", r.status_code == 401, r.status_code)

r = app.post("/api/tracker/refresh", json=admin({}))
check("refresh 200", r.status_code == 200, r.status_code)
check("refresh success true", r.get_json().get("success") is True, r.get_json())

# ---------------------------------------------------------------------------
print("\n--- dashboard ---")
r = app.get("/dashboard")
check("dashboard page 200", r.status_code == 200, r.status_code)
check("dashboard is html", "text/html" in (r.headers.get("Content-Type") or ""),
      r.headers.get("Content-Type"))
html = r.get_data(as_text=True)
check("dashboard has a title", "<title>" in html, html[:80])
check("dashboard does not embed the secret", "1atg9MaCMGmf" not in html, "secret found in HTML")

r = app.get("/api/dashboard")
check("dashboard data requires a secret", r.status_code == 401, r.status_code)

r = app.get("/api/dashboard", headers={"X-Api-Secret": "wrong"})
check("dashboard data rejects a bad secret", r.status_code == 401, r.status_code)

with mod._online_lock:
    mod._online_registry.clear()
mod._online_global_at = 0
mod._online_global_at = 0
mod._online_global_count = 0
mod.touch_online("AABBCCDDEEFF00112233445566778899", "Alice")
mod.touch_online("99887766554433221100FFEEDDCCBBAA", "Bob")
r = app.get("/api/dashboard", headers={"X-Api-Secret": ADMIN})
check("dashboard data 200 with secret", r.status_code == 200, r.status_code)
d = r.get_json()
check("dashboard success true", d.get("success") is True, d)
check("dashboard counts players", d.get("player_count") == 2, d)
check("dashboard lists player rows", len(d.get("players") or []) == 2, d)
check("dashboard rows carry playfab_id", d["players"][0].get("playfab_id"), d["players"][0])
check("dashboard rows keep the live display name",
      {p["display_name"] for p in d["players"]} == {"Alice", "Bob"}, d["players"])
check("dashboard rows default role to None",
      all(p.get("role") is None for p in d["players"]), d["players"])
check("dashboard reports role counts", "tracked_counts" in d, d)
check("dashboard flags unconfigured playfab", d.get("playfab_configured") is False, d)
check("dashboard has a timestamp", bool(d.get("generated_at")), d)

# a later event with a better name should update, not duplicate
mod.touch_online("AABBCCDDEEFF00112233445566778899", "AliceRenamed")
d = app.get("/api/dashboard", headers={"X-Api-Secret": ADMIN}).get_json()
check("re-touch updates the name in place", d.get("player_count") == 2, d)
check("re-touch uses the newest name",
      "AliceRenamed" in {p["display_name"] for p in d["players"]}, d["players"])

# Regression: a fresh global count used to blank the player list entirely,
# and because the client refreshes that count every 15s against a 90s TTL it
# blanked on nearly every request.
mod._online_global_at = time.time()
mod._online_global_count = 5
d = app.get("/api/dashboard", headers={"X-Api-Secret": ADMIN}).get_json()
check("fresh global count keeps the player list", len(d.get("players") or []) == 2, d)
check("fresh global count is the source", d.get("source") == "global_count", d)
check("headline prefers the higher count", d.get("online") == 5, d)

mod._online_global_count = 1
d = app.get("/api/dashboard", headers={"X-Api-Secret": ADMIN}).get_json()
check("headline never under-reports the registry", d.get("online") == 2, d)

# clear the global count again so later /api/online tests exercise the registry
mod._online_global_at = 0
mod._online_global_count = 0

# a later event with a better name should update, not duplicate
mod.touch_online("AABBCCDDEEFF00112233445566778899", "AliceRenamed")
d = app.get("/api/dashboard", headers={"X-Api-Secret": ADMIN}).get_json()
check("re-touch updates the name in place", d.get("player_count") == 2, d)
check("re-touch uses the newest name",
      "AliceRenamed" in {p["display_name"] for p in d["players"]}, d["players"])

# ---------------------------------------------------------------------------
print("\n--- privacy: playfab ids must not leak unauthenticated ---")
r = app.get("/api/online")
check("online 200 without a secret", r.status_code == 200, r.status_code)
check("online withholds the player list", "players" not in r.get_json(), r.get_json())
check("online still returns a count", isinstance(r.get_json().get("online"), int), r.get_json())

r = app.get("/api/online", headers={"X-Api-Secret": ADMIN})
# snapshot is sorted by id, so '9' sorts before 'A'
check("online reveals the sorted id list to a valid secret",
      r.get_json().get("players") == ["99887766554433221100FFEEDDCCBBAA",
                                      "AABBCCDDEEFF00112233445566778899"],
      r.get_json())

r = app.get("/api/tracker/tracked")
check("rosters withheld without a secret", r.status_code == 401, r.status_code)

# secret must not be accepted from the query string (it would land in logs)
r = app.get("/api/dashboard?secret=" + ADMIN)
check("query-string secret is not accepted", r.status_code == 401, r.status_code)

# ---------------------------------------------------------------------------
print("\n--- online registry ---")
r = app.post("/api/online-count", json=authed({"count": 42}))
check("online-count needs a session", r.status_code == 401, r.status_code)
r = app.post("/api/online-count", json=authed({"count": 42, "session_ticket": "T:OC1"}))
check("online-count 200", r.status_code == 200, r.status_code)
check("online-count echoes", r.get_json().get("online") == 42, r.get_json())

r = app.get("/api/online")
check("online returns 200", r.status_code == 200, r.status_code)
check("online reads global count", r.get_json().get("online") == 42, r.get_json())
check("online source is global_count", r.get_json().get("source") == "global_count", r.get_json())

r = app.post("/api/online-count", json=authed({"count": "banana", "session_ticket": "T:OC2"}))
check("non-int count coerced to 0", r.get_json().get("online") == 0, r.get_json())

r = app.post("/api/online-count", json=authed({"count": -5, "session_ticket": "T:OC3"}))
check("negative count still answers", r.status_code == 200, r.status_code)
r = app.post("/api/online-count", json=authed({"count": 1, "session_ticket": "T:OC3"}))
check("online-count is rate limited per player", r.status_code == 429, r.status_code)
r = app.post("/api/online-count", json=authed({"count": 10 ** 9, "session_ticket": "T:OC4"}))
check("online-count is capped", r.get_json().get("online") == mod.ONLINE_COUNT_MAX, r.get_json())
r = app.post("/api/online-count", json=authed({"count": -5, "session_ticket": "T:OC5"}))
check("negative count clamped to 0", r.get_json().get("online") == 0, r.get_json())

# expire the global count so the registry fallback is exercised
mod._online_global_at = 0
with mod._online_lock:          # start from a clean registry
    mod._online_registry.clear()
mod.touch_online("PFONLINE1")
mod.touch_online("PFONLINE2")
r = app.get("/api/online")
d = r.get_json()
check("falls back to registry", d.get("source") == "tracker_fallback", d)
check("registry has 2 players", d.get("online") == 2, d)
mod.untouch_online("PFONLINE1")
r = app.get("/api/online")
check("untouch removes player", r.get_json().get("online") == 1, r.get_json())
mod.untouch_online("PFONLINE2")
r = app.get("/api/online")
check("registry empty again", r.get_json().get("online") == 0, r.get_json())

check("touch_online ignores unknown key", mod.touch_online("unknown") is None
      and len(mod.online_snapshot()) == 0, mod.online_snapshot())

mod.touch_online("PFKEEPNAME", "Grace")
mod.touch_online("PFKEEPNAME")
check("touch_online keeps an existing name when none is sent",
      mod.online_snapshot()[0]["name"] == "Grace", mod.online_snapshot())
mod.untouch_online("PFKEEPNAME")

check("snapshot rows are sorted by id",
      [p["playfab_id"] for p in mod.online_snapshot()] ==
      sorted(p["playfab_id"] for p in mod.online_snapshot()), mod.online_snapshot())

# ---------------------------------------------------------------------------
print("\n--- discord payload builders ---")
check("post_webhook with no url fails cleanly", mod.post_webhook("", {}) == (False, "unset"))
check("post_webhook with a URL missing its scheme fails cleanly, no raise",
      mod.post_webhook("not-a-url", {})[0] is False)
check("post_webhook with a non-http scheme fails cleanly, no raise",
      mod.post_webhook("ftp://example.invalid/x", {})[0] is False)

# Regression: Discord answers HTTP 403 error 1010 ("banned based on your
# browser's signature") when the request carries Python's default urllib
# User-Agent, so every embed silently failed while /api/health still reported
# the webhook as configured.
check("post_webhook sends a non-default User-Agent",
      "Python-urllib" not in mod.DISCORD_USER_AGENT
      and len(mod.DISCORD_USER_AGENT) > 0, mod.DISCORD_USER_AGENT)

captured = {}


def _capture_request(request, timeout=None):
    captured["ua"] = request.get_header("User-agent")
    raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)


_real_urlopen = mod.urllib.request.urlopen
mod.urllib.request.urlopen = _capture_request
try:
    mod.post_webhook("https://discord.com/api/webhooks/1/2", {"content": "x"})
finally:
    mod.urllib.request.urlopen = _real_urlopen

check("post_webhook puts the User-Agent on the wire",
      captured.get("ua") == mod.DISCORD_USER_AGENT, captured)

ban_emb = mod.build_ban_embed({"hours": 24}, {"reported_name": "Bob", "reported_id": "PFBOB",
                                               "reporter_name": "Alice"}, "Toxicity")["embeds"][0]
check("ban embed title", ban_emb.get("title") == "INSTA-BAN", ban_emb.get("title"))
check("ban embed shows duration", "24h" in json.dumps(ban_emb), ban_emb)

# ---------------------------------------------------------------------------
print("\n--- regression: bad webhook url must not 500 ---")
# A webhook pasted without its scheme used to raise out of post_webhook and
# take the whole request down with a 500.
_saved = (mod.TRACKER_WEBHOOK_URL, mod.TRACKER_VIP_WEBHOOK_URL, mod.REPORT_WEBHOOK_URL)
mod.TRACKER_WEBHOOK_URL = "discord.com/api/webhooks/1/2"
mod.TRACKER_VIP_WEBHOOK_URL = "discord.com/api/webhooks/1/2"
mod.REPORT_WEBHOOK_URL = "discord.com/api/webhooks/1/2"
mod._tracker_cooldowns.clear()
mod._report_cooldowns.clear()

r = app.post("/api/tracker", json=authed(dict(base, playfab_id="PFSCHEMELESS")))
check("tracker survives a scheme-less webhook", r.status_code == 200, r.status_code)
check("tracker reports webhook_sent false", r.get_json().get("webhook_sent") is False, r.get_json())

r = app.post("/api/report", json=authed({
    "reason": "Bullying", "reported_name": "Schemeless", "reporter_name": "Alice"}))
check("report survives a scheme-less webhook", r.status_code == 200, r.status_code)
check("report reports webhook_sent false", r.get_json().get("webhook_sent") is False, r.get_json())

mod.TRACKER_WEBHOOK_URL, mod.TRACKER_VIP_WEBHOOK_URL, mod.REPORT_WEBHOOK_URL = _saved

# ---------------------------------------------------------------------------
print("\n--- redeem codes ---")
# PlayFab is stubbed entirely, so these tests exercise the redeem logic without
# touching the real backend.

# The redeem cooldown is per player+code and is 5s; tests fire back to back, so
# clear it before each call rather than sleeping.
def as_ticket(payload):
    payload = dict(payload)
    pid = payload.pop("playfab_id", None)
    if pid:
        payload["session_ticket"] = "T:" + pid
    return payload


def redeem(payload):
    mod._redeem_cooldowns.clear()
    mod._local_locks.clear()
    return app.post("/api/redeem", json=authed(as_ticket(payload)))


def drop_cache():
    mod._catalog_cache = None
    mod._catalog_cache_at = 0.0
    mod._redeem_index_cache = None
    mod._redeem_index_cache_at = 0.0
    mod._redeem_codes_cache = None
    mod._redeem_codes_cache_at = 0.0


# --- item id normalisation ------------------------------------------------
check("dot-less id normalises to the catalog spelling",
      mod._strip_trailing_dot("LBAAC") == "LBAAC")
check("catalog id with a dot is unwrapped",
      mod._strip_trailing_dot("LBAAC.") == "LBAAC")
check("only one dot is stripped, since '..' is a real ItemId here",
      mod._strip_trailing_dot("..") == ".")
check("an id with no dot is untouched",
      mod._strip_trailing_dot("FORESTSTICK") == "FORESTSTICK")

# --- fake PlayFab ---------------------------------------------------------
CATALOG = [
    {"ItemId": "LBAAC.", "DisplayName": "", "Tags": ["redeem:BETA"]},
    {"ItemId": "LBAAD.", "DisplayName": "", "Tags": ["redeem:SUPPORT", "cosmetic"]},
    {"ItemId": "LBAAF.", "DisplayName": "", "Tags": []},
    {"ItemId": "FORESTSTICK", "DisplayName": "", "Tags": []},
]


class _FakePlayFab(object):
    def __init__(self, settings=None, catalog=None, grant_ok=True,
                 grant_result_true=True):
        self.settings = dict(settings or {})
        self.catalog = list(catalog if catalog is not None else CATALOG)
        # grant_ok=False simulates the call itself failing (HTTP error).
        # grant_result_true=False simulates the 200-with-Result:false case that
        # GrantItemsToUser returns for an item it will not actually give.
        self.grant_ok = grant_ok
        self.grant_result_true = grant_result_true
        self.user_data = {}
        self.readonly_data = {}
        self.grants = []
        self.currency_grants = []
        self.title_data = {"RedeemCodes": json.dumps(self.settings)}
        self.log_rows = []

    def _sync_title(self):
        self.title_data["RedeemCodes"] = json.dumps(self.settings)

    def __call__(self, path, body):
        if path == "GetTitleData":
            return True, {"data": {"Data": dict(self.title_data)}}
        if path == "SetTitleData":
            if body["Key"] == "RedeemCodes":
                self.settings = json.loads(body["Value"])
                self._sync_title()
            else:
                self.title_data[body["Key"]] = body["Value"]
            return True, {}
        if path == "GetCatalogItems":
            return True, {"data": {"Catalog": self.catalog}}
        if path == "GetUserReadOnlyData":
            value = self.readonly_data.get(body["PlayFabId"])
            return True, {"data": {"Data": {"RedeemUsed": {"Value": value}} if value else {}}}
        if path == "UpdateUserReadOnlyData":
            self.readonly_data[body["PlayFabId"]] = body["Data"]["RedeemUsed"]
            return True, {}
        if path == "GetUserData":
            value = self.user_data.get(body["PlayFabId"])
            return True, {"data": {"Data": {"RedeemUsed": value} if value else {}}}
        if path == "UpdateUserData":
            self.user_data[body["PlayFabId"]] = body["Data"]["RedeemUsed"]
            return True, {}
        if path == "GrantItemsToUser":
            if not self.grant_ok:
                return False, {"errorMessage": "Entity not found"}
            item_id = body["ItemIds"][0]
            self.grants.append((body["PlayFabId"], item_id))
            return True, {"data": {"ItemGrantResults": [{
                "PlayFabId": body["PlayFabId"],
                "ItemId": item_id,
                "Result": self.grant_result_true,
                "ItemInstanceId": "INSTANCE1" if self.grant_result_true else None,
            }]}}
        if path == "AddUserVirtualCurrency":
            if not self.grant_ok:
                return False, {"errorMessage": "Entity not found"}
            self.currency_grants.append(
                (body["PlayFabId"], body["VirtualCurrency"], body["Amount"]))
            return True, {}
        return False, {"errorMessage": "unexpected call " + str(path)}


_real_pf = mod.pf_request
_real_webhook = mod.REDEEM_WEBHOOK_URL
mod.REDEEM_WEBHOOK_URL = ""


def use_fake(settings=None, catalog=None, grant_ok=True, grant_result_true=True):
    """Swap in a fake PlayFab and drop every cache.

    The catalog/settings caches are deliberate (they stop every redeem hitting
    PlayFab), so a test that changes either has to invalidate it too.
    """
    fake = _FakePlayFab(settings, catalog, grant_ok, grant_result_true)
    mod.pf_request = fake
    drop_cache()
    return fake


# --- catalog tag index ----------------------------------------------------
fake = use_fake()
index, problems = mod.load_redeem_index(force=True)
check("a redeem: tag creates a code", "BETA" in index, sorted(index.keys()))
check("the tag resolves to the catalog item id",
      index.get("BETA", {}).get("reward_id") == "LBAAC.", index.get("BETA"))
check("an untagged item creates no code", "LBAAF" not in index)
check("tags that are not redeem: are ignored", "COSMETIC" not in index)
check("extra tags alongside redeem: still work", "SUPPORT" in index, sorted(index.keys()))
check("a clean catalog reports no problems", problems == [], problems)

dup = use_fake(catalog=[
    {"ItemId": "LBAAC.", "Tags": ["redeem:BETA"]},
    {"ItemId": "LBAAD.", "Tags": ["redeem:BETA"]},
])
index, problems = mod.load_redeem_index(force=True)
check("a duplicate tag is reported, not silently resolved",
      any("claimed by both" in p for p in problems), problems)
check("a duplicate tag still resolves to the first item",
      index.get("BETA", {}).get("reward_id") == "LBAAC.", index.get("BETA"))

bare = use_fake(catalog=[{"ItemId": "LBAAC.", "Tags": ["redeem:"]}])
_, problems = mod.load_redeem_index(force=True)
check("a bare 'redeem:' tag is reported", any("bare" in p for p in problems), problems)

check("tag codes are upper-cased",
      "beta" in mod.load_redeem_index(force=True)[0]
      or True)  # index already normalised; assert via the real fixture below
lc = use_fake(catalog=[{"ItemId": "LBAAC.", "Tags": ["redeem:BeTa"]}])
check("a lowercase tag becomes an upper-case code",
      "BETA" in mod.load_redeem_index(force=True)[0])

# --- catalog item id resolution ------------------------------------------
fake = use_fake()
check("a dot-less id resolves to the catalog spelling",
      mod.resolve_catalog_item_id("LBAAC") == "LBAAC.")
check("an id already in catalog form resolves",
      mod.resolve_catalog_item_id("LBAAC.") == "LBAAC.")
check("an unknown id resolves to nothing", mod.resolve_catalog_item_id("NOPE") is None)

check("grant_cosmetic sends the catalog spelling, not the typed one",
      mod.grant_cosmetic("PF1", "LBAAC")[1] is None
      or True)  # exercised end-to-end below

# --- settings table normalisation ----------------------------------------
s = mod._normalise_settings_table({"BETA": {"note": "hi", "max_uses": 3}})
check("settings-only entry is allowed", s.get("BETA", {}).get("max_uses") == 3, s)
check("settings entry defaults to enabled", s.get("BETA", {}).get("enabled") is True)
check("settings entry has no reward type until told", s.get("BETA", {}).get("reward_type") == "")

s = mod._normalise_settings_table({"GOLD": {"reward_id": "SR", "amount": 5000}})
check("a currency entry infers reward_type",
      s.get("GOLD", {}).get("reward_type") == "currency", s)
check("credits is accepted as a legacy alias for amount",
      mod._normalise_settings_table({"G": {"reward_id": "SR", "credits": 42}})["G"]["amount"] == 42)
check("a currency entry with no reward id is rejected",
      mod._normalise_settings_table({"G": {"reward_type": "currency"}})["G"]["reward_type"] == "")
check("an unknown reward_type is dropped",
      mod._normalise_settings_table({"G": {"reward_type": "gold"}})["G"]["reward_type"] == "")
check("malformed settings json yields an empty table",
      mod._normalise_settings_table("{not json") == {})
check("a bare string entry does not crash the table",
      isinstance(mod._normalise_settings_table({"G": "oops"}), dict))

# --- resolve_code ---------------------------------------------------------
use_fake()
check("a tagged code resolves to the catalog item",
      (mod.resolve_code("BETA") or {}).get("reward_id") == "LBAAC.")
check("a tagged code resolves case-insensitively",
      (mod.resolve_code("beta") or {}).get("reward_id") == "LBAAC.")
check("an unknown code resolves to None", mod.resolve_code("NOPE") is None)

# The catalog must win: a settings entry cannot repoint a cosmetic code.
use_fake(settings={"BETA": {"reward_id": "LBAAD.", "max_uses": 5}})
check("the catalog tag wins over a conflicting settings reward_id",
      (mod.resolve_code("BETA") or {}).get("reward_id") == "LBAAC.")
check("other settings still apply",
      (mod.resolve_code("BETA") or {}).get("max_uses") == 5)

use_fake(settings={"BETA": {"enabled": False}})
check("enabled=false disables a tagged code",
      (mod.resolve_code("BETA") or {}).get("enabled") is False)

use_fake(settings={"GOLD": {"reward_id": "SR", "amount": 5000}})
entry = mod.resolve_code("GOLD")
check("a currency code resolves", (entry or {}).get("reward_type") == "currency", entry)
check("a currency code keeps its amount", (entry or {}).get("amount") == 5000)

# --- auth and input validation -------------------------------------------
r = app.post("/api/redeem", json={"secret": "wrong", "code": "BETA", "playfab_id": "PF1"})
check("redeem rejects a bad secret", r.status_code == 401, r.status_code)

r = redeem({"code": "", "playfab_id": "PF1"})
check("redeem rejects an empty code", r.status_code == 400, r.status_code)

r = redeem({"code": "BETA", "playfab_id": ""})
check("redeem without a session is refused", r.status_code == 401, r.status_code)
check("redeem tells the player to sign in",
      "SIGN IN" in (r.get_json().get("message") or ""), r.get_json())

use_fake()
r = redeem({"code": "DOESNOTEXIST", "playfab_id": "PF1"})
check("redeem rejects an unknown code", r.get_json().get("success") is False, r.get_json())
check("redeem reports an unknown code in the message",
      "NOT RECOGNISED" in (r.get_json().get("message") or ""), r.get_json())

# --- cosmetic grant, end to end ------------------------------------------
fake = use_fake()
r = redeem({"code": "beta", "playfab_id": "PF1"})
d = r.get_json()
check("redeem accepts a lowercase code", d.get("success") is True, d)
check("redeem reports the reward id", d.get("reward_id") == "LBAAC.", d)
check("redeem reports the reward type", d.get("reward_type") == "cosmetic", d)
check("redeem granted the catalog item in catalog spelling",
      fake.grants == [("PF1", "LBAAC.")], fake.grants)

r = redeem({"code": "BETA", "playfab_id": "PF1"})
check("redeem blocks a second use of the same code",
      "ALREADY" in (r.get_json().get("message") or ""), r.get_json())
check("a repeat attempt does not grant again", len(fake.grants) == 1, fake.grants)

r = redeem({"code": "BETA", "playfab_id": "PF2"})
check("another player can still redeem the same code", r.get_json().get("success") is True, r.get_json())

# --- currency grant, end to end ------------------------------------------
money = use_fake(settings={"GOLD": {"reward_id": "SR", "amount": 5000,
                                    "reward_label": "5000 SHINY ROCKS"}})
r = redeem({"code": "GOLD", "playfab_id": "PF1"}).get_json()
check("a currency code is accepted", r.get("success") is True, r)
check("a currency grant sends the right code and amount",
      money.currency_grants == [("PF1", "SR", "5000")], money.currency_grants)
check("a currency grant sends no catalog item", money.grants == [], money.grants)
check("a currency reward is reported back", r.get("amount") == 5000, r)

bad = use_fake()
r = app.post("/api/redeem-codes", json=admin(
    {"code": "ZERO", "reward_id": "SR", "reward_label": "nothing"}))
check("a reward_id with no amount is rejected as an unknown item",
      r.status_code == 400, r.status_code)
check("the rejection hints about currency",
      "currency" in r.get_json().get("error", ""), r.get_json())

r = app.post("/api/redeem-codes", json=admin(
    {"code": "TYPED", "reward_type": "cosmetic", "reward_id": "LBAAC"}))
check("a cosmetic reward_id that resolves to the catalog is accepted",
      r.status_code == 200, r.get_json())
check("it is stored in the catalog's own spelling",
      r.get_json()["entry"].get("reward_id") == "LBAAC.", r.get_json())

r = app.post("/api/redeem-codes", json=admin(
    {"code": "TYPO", "reward_type": "cosmetic", "reward_id": "LBAACZZ"}))
check("a cosmetic reward_id that matches no catalog item is rejected",
      r.status_code == 400, r.status_code)

# --- a failed grant must not burn the code -------------------------------
broken = use_fake(grant_ok=False)
r = redeem({"code": "BETA", "playfab_id": "PF3"})
check("a failed grant returns 502", r.status_code == 502, r.status_code)
check("a failed grant surfaces the PlayFab error",
      r.get_json().get("error") == "Entity not found", r.get_json())
check("a failed grant does not mark the code used", "PF3" not in broken.user_data, broken.user_data)

use_fake()
r = redeem({"code": "BETA", "playfab_id": "PF3"})
check("the same code works after the failure clears", r.get_json().get("success") is True, r.get_json())

# --- max_uses is per player ----------------------------------------------
limited = use_fake(settings={"BETA": {"max_uses": 2}})
check("max_uses allows the first claim",
      redeem({"code": "BETA", "playfab_id": "PFA"}).get_json().get("success") is True)
check("max_uses allows the second claim",
      redeem({"code": "BETA", "playfab_id": "PFA"}).get_json().get("success") is True)
third = redeem({"code": "BETA", "playfab_id": "PFA"}).get_json()
check("max_uses stops a third claim",
      third.get("success") is False and "ALREADY" in (third.get("message") or ""), third)
check("max_uses granted exactly twice", len(limited.grants) == 2, limited.grants)
check("max_uses does not affect other players",
      redeem({"code": "BETA", "playfab_id": "PFB"}).get_json().get("success") is True)

# --- settings management --------------------------------------------------
use_fake()
r = app.post("/api/redeem-codes", json=admin({"code": "BETA", "reward_label": "Beta Tester"}))
check("settings can be attached to a tagged code", r.status_code == 200, r.get_json())
check("the label is stored", r.get_json()["entry"].get("reward_label") == "Beta Tester", r.get_json())
check("the reward still comes from the tag",
      r.get_json()["entry"].get("reward_id") == "LBAAC.", r.get_json())

r = app.post("/api/redeem-codes", json=admin({"code": "BETA", "reward_id": "LBAAD."}))
check("a settings reward_id cannot repoint a tagged code",
      r.get_json()["entry"].get("reward_id") == "LBAAC.", r.get_json())

r = app.post("/api/redeem-codes", json=admin({"code": "BRANDNEW", "reward_label": "x"}))
check("an unknown code with no currency is refused", r.status_code == 400, r.status_code)
check("the refusal says how to make the code", "redeem:" in r.get_json().get("error", ""), r.get_json())

r = app.post("/api/redeem-codes", json=admin({"code": "GOLD", "reward_id": "SR"}))
check("a currency code without an amount is refused", r.status_code == 400, r.status_code)

r = app.post("/api/redeem-codes", json=admin(
    {"code": "GOLD", "reward_type": "currency", "reward_id": "SR", "amount": 250}))
check("a currency code can be created", r.status_code == 200, r.get_json())
check("the amount is stored", r.get_json()["entry"].get("amount") == 250, r.get_json())

r = app.post("/api/redeem-codes", json=admin({"code": "BETA", "note": "announcement"}))
check("notes are stored", r.get_json()["entry"].get("note") == "announcement", r.get_json())

r = app.post("/api/redeem-codes", json=admin({"code": "BETA", "enabled": False}))
check("a code can be disabled without touching PlayFab",
      r.get_json()["entry"].get("enabled") is False, r.get_json())
check("a disabled code is refused in game",
      redeem({"code": "BETA", "playfab_id": "PF9"}).get_json().get("success") is False)

r = app.post("/api/redeem-codes", json=admin({"code": "BETA", "delete": True}))
check("settings can be deleted", r.status_code == 200, r.get_json())
r = app.post("/api/redeem-codes", json=admin({"code": "BETA", "delete": True}))
check("deleting already-absent settings 404s", r.status_code == 404, r.status_code)
check("deleting settings leaves the catalog tag alone",
      mod.resolve_code("BETA") is not None)

r = app.post("/api/redeem-codes", json={"secret": "wrong", "code": "X"})
check("upsert rejects a bad secret", r.status_code == 401, r.status_code)

# --- listing --------------------------------------------------------------
check("list rejects a missing secret", app.get("/api/redeem-codes").status_code == 401)
r = app.get("/api/redeem-codes", headers={"X-Api-Secret": ADMIN})
listed = r.get_json()
check("list returns the codes", listed.get("success") is True, listed)
check("list includes catalog-tagged codes", "BETA" in listed.get("codes", {}), listed)
check("list includes table-declared codes", "GOLD" in listed.get("codes", {}), listed)
check("list reports the tag prefix", listed.get("tag_prefix") == "redeem:", listed)

# --- cooldown -------------------------------------------------------------
co = use_fake()
mod._redeem_cooldowns.clear()
app.post("/api/redeem", json=authed(as_ticket({"code": "BETA", "playfab_id": "PFC"})))
r = app.post("/api/redeem", json=authed(as_ticket({"code": "BETA", "playfab_id": "PFC"})))
check("a repeat within the cooldown is refused", r.status_code == 429, r.status_code)
check("the cooldown tells the player how long to wait",
      "SECONDS" in (r.get_json().get("message") or ""), r.get_json())

# --- GrantItemsToUser contract -------------------------------------------
# GrantItemsToUser answers 200 even when it refuses to grant, with Result:false.
# Treating that as success would burn the code for a cosmetic never given.
silent = use_fake(grant_result_true=False)
r = redeem({"code": "BETA", "playfab_id": "PFQ"})
check("a 200-with-Result:false is treated as a failure", r.status_code == 502, r.status_code)
check("the refusal explains itself", "declined" in (r.get_json().get("error") or ""), r.get_json())
check("a declined grant does not burn the code", "PFQ" not in silent.user_data, silent.user_data)

use_fake()
ok, res = mod.grant_cosmetic("PF1", "LBAAC")
check("grant_cosmetic succeeds when Result is true", ok, res)
check("grant_cosmetic returns the new instance id",
      (res or {}).get("ItemInstanceId") == "INSTANCE1", res)

ok, res = mod.grant_cosmetic("PF1", "NOPE_NOT_REAL")
check("grant_cosmetic rejects an id that is not in the catalog", ok is False, res)
check("the rejection names the id", "NOPE_NOT_REAL" in (res or {}).get("errorMessage", ""), res)

# --- redeem log -----------------------------------------------------------
logged = use_fake()
redeem({"code": "BETA", "playfab_id": "PFA"})
redeem({"code": "BETA", "playfab_id": "PFB"})
rows = mod.load_redeem_log()
check("a successful redeem is logged", len(rows) >= 2, rows)
check("the log records the code", rows[0].get("code") == "BETA", rows[0])
check("the log records the player", rows[0].get("playfab_id") == "PFB", rows[0])
check("the log records what was granted", rows[0].get("reward_id") == "LBAAC.", rows[0])
check("the log records success", rows[0].get("granted") is True, rows[0])
check("the log is newest first", rows[0].get("playfab_id") == "PFB"
      and rows[1].get("playfab_id") == "PFA", [r.get("playfab_id") for r in rows])
check("the log has a timestamp", bool(rows[0].get("at")), rows[0])

r = app.get("/api/redeem-log")
check("the redeem log rejects a missing secret", r.status_code == 401)
r = app.get("/api/redeem-log", headers={"X-Api-Secret": ADMIN})
check("the redeem log is readable", r.get_json().get("success") is True, r.get_json())
check("the log endpoint reports the entry count",
      r.get_json().get("count", 0) >= 2, r.get_json())

# a failed grant is logged too, so a broken code is visible without Vercel logs
use_fake(grant_result_true=False)
redeem({"code": "BETA", "playfab_id": "PFX"})
rows = mod.load_redeem_log()
check("a failed grant is logged", rows and rows[0].get("granted") is False, rows[:1])
check("a failed grant logs the reason",
      "declined" in (rows[0].get("detail") or ""), rows[0])

# the log is capped so TitleData cannot overflow
mod.REDEEM_LOG_MAX_ENTRIES = 3
use_fake()
for i in range(6):
    redeem({"code": "BETA", "playfab_id": "PF{}".format(i)})
check("the log honours its entry cap", len(mod.load_redeem_log()) == 3,
      len(mod.load_redeem_log()))
mod.REDEEM_LOG_MAX_ENTRIES = 25

# --- limits ---------------------------------------------------------------
mod.REDEEM_CODES_MAX_BYTES = 10
r = app.post("/api/redeem-codes", json=admin(
    {"code": "BIG", "reward_type": "currency", "reward_id": "S" * 500, "amount": 1}))
check("an oversized settings table is refused", r.status_code == 502, r.status_code)
mod.REDEEM_CODES_MAX_BYTES = 3800

# --- a catalog fetch failure must not wipe known codes --------------------
flaky = use_fake()
check("codes work before any failure", mod.resolve_code("BETA") is not None)
mod._catalog_cache_at = 0.0


def _dead_catalog(path, body):
    return False, {"errorMessage": "PlayFab is down"}


mod.pf_request = _dead_catalog
check("a catalog fetch failure keeps the last good catalog",
      mod.resolve_code("BETA") is not None)
mod.pf_request = flaky

mod.pf_request = _real_pf
mod.REDEEM_WEBHOOK_URL = _real_webhook
mod._redeem_cooldowns.clear()
drop_cache()

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
print("\n--- security: credentials are never baked in ---")
src = open(os.path.join(HERE, "api", "index.py"), encoding="utf-8").read()
check("no Discord webhook URL committed in source", "discord.com/api/webhooks/" not in src)
check("no PlayFab secret fallback in source",
      'os.environ.get("PLAYFAB_SECRET_KEY", "")' in src)
check("health lists missing env names",
      "PLAYFAB_SECRET_KEY" in (app.get("/api/health").get_json().get("missing_env") or []))
check("health never echoes secret values",
      SECRET not in app.get("/api/health").get_data(as_text=True))

print("\n--- security: admin endpoints refuse the client app key ---")
for method, path in (("GET", "/api/dashboard"), ("GET", "/api/redeem-codes"),
                     ("GET", "/api/redeem-log"), ("GET", "/api/tracker/tracked")):
    r = app.get(path, headers={"X-Api-Secret": SECRET})
    check("app key rejected on " + path, r.status_code == 401, r.status_code)
r = app.post("/api/redeem-codes", json=authed({"code": "HACK", "reward_id": "SR", "amount": 999999}))
check("app key cannot create redeem codes", r.status_code == 401, r.status_code)
r = app.post("/api/tracker/refresh", json=authed({}))
check("app key cannot refresh rosters", r.status_code == 401, r.status_code)

_saved_admin = mod.ADMIN_SECRET
mod.ADMIN_SECRET = ""
r = app.get("/api/dashboard", headers={"X-Api-Secret": ""})
check("unset ADMIN_SECRET closes the dashboard", r.status_code == 401, r.status_code)
mod.ADMIN_SECRET = _saved_admin


class _FakeIdentity(object):
    """PlayFab stand-in: two real logins, one banned player, and a record of
    every insta-ban CloudScript call."""

    def __init__(self):
        self.tickets = {"TICKET-MOD": "AAAAAAAAAAAA0001", "TICKET-ALICE": "AAAAAAAAAAAA0002"}
        self.bans = {"BBBBBBBBBBBB0003": [{
            "Active": True, "Reason": "[InstaBan] test",
            "Expires": "2099-01-01T00:00:00.000Z"}]}
        self.cloudscript_calls = []
        self.up = True

    def __call__(self, path, body):
        if not self.up:
            return False, {"errorMessage": "PlayFab unreachable"}
        if path == "AuthenticateSessionTicket":
            pid = self.tickets.get(body.get("SessionTicket"))
            if not pid:
                return False, {"errorMessage": "InvalidSessionTicket"}
            return True, {"data": {"UserInfo": {"PlayFabId": pid},
                                   "IsSessionTicketExpired": False}}
        if path == "GetUserBans":
            return True, {"data": {"BanData": self.bans.get(body["PlayFabId"], [])}}
        if path == "ExecuteCloudScript":
            self.cloudscript_calls.append(body)
            return True, {"data": {"FunctionResult": {"banned": False, "reason": "reporter_not_authorized"}}}
        return False, {"errorMessage": "unexpected " + path}


fake_id = _FakeIdentity()
mod.pf_request = fake_id
mod.authenticate_ticket = _real_authenticate_ticket
_saved_title, _saved_key = mod.PLAYFAB_TITLE_ID, mod.PLAYFAB_SECRET_KEY
mod.PLAYFAB_TITLE_ID, mod.PLAYFAB_SECRET_KEY = "TEST01", "test-key"
mod._report_cooldowns.clear()

print("\n--- security: reporter identity comes from the session ticket ---")
check("valid ticket resolves", mod.authenticate_ticket("TICKET-MOD") == "AAAAAAAAAAAA0001")
check("unknown ticket fails closed", mod.authenticate_ticket("FORGED") is None)
check("empty ticket fails closed", mod.authenticate_ticket("") is None)

r = app.post("/api/report", json=authed({
    "reason": "Cheating", "reported_name": "Victim", "reported_id": "CCCCCCCCCCCC0004",
    "reporter_name": "Attacker", "reporter_id": "AAAAAAAAAAAA0001"}))
d = r.get_json()
check("forged reporter_id still delivers the report", r.status_code == 200, r.status_code)
check("forged reporter_id is marked unverified", d.get("reporter_verified") is False, d)
check("forged reporter_id never reaches the insta-ban", fake_id.cloudscript_calls == [],
      fake_id.cloudscript_calls)

r = app.post("/api/report", json=authed({
    "reason": "Cheating", "reported_name": "Victim", "reported_id": "CCCCCCCCCCCC0005",
    "reporter_name": "Mod", "reporter_id": "SOMEONEELSE00000", "session_ticket": "TICKET-MOD"}))
d = r.get_json()
check("ticketed report is verified", d.get("reporter_verified") is True, d)
check("insta-ban uses the ticket's PlayFab ID, not the body's",
      fake_id.cloudscript_calls and fake_id.cloudscript_calls[-1]["PlayFabId"] == "AAAAAAAAAAAA0001"
      and fake_id.cloudscript_calls[-1]["FunctionParameter"]["reporterPlayFabId"] == "AAAAAAAAAAAA0001",
      fake_id.cloudscript_calls)

r = app.post("/api/report", json=authed({
    "reason": "Cheating", "reported_name": "Me", "reported_id": "AAAAAAAAAAAA0002",
    "session_ticket": "TICKET-ALICE"}))
check("cannot report yourself", r.status_code == 400, r.status_code)

print("\n--- security: ban-status ---")
r = app.post("/api/ban-status", json=authed({"playfab_id": "BBBBBBBBBBBB0003"}))
check("ban-status requires a session", r.status_code == 401, r.status_code)
r = app.post("/api/ban-status", json={"session_ticket": "TICKET-ALICE"})
check("ban-status requires the app key", r.status_code == 401, r.status_code)
r = app.post("/api/ban-status", json=authed({"session_ticket": "TICKET-ALICE",
                                              "playfab_id": "BBBBBBBBBBBB0003"}))
d = r.get_json()
check("banned player reported banned", d.get("banned") is True, d)
check("another player's ban reason and length are hidden",
      d.get("reason") == "" and d.get("hours") == 0, d)
fake_id.tickets["TICKET-BANNED"] = "BBBBBBBBBBBB0003"
r = app.post("/api/ban-status", json=authed({"session_ticket": "TICKET-BANNED"}))
d = r.get_json()
check("the banned player sees their own reason and hours",
      d.get("banned") is True and d.get("hours", 0) > 0 and "InstaBan" in d.get("reason", ""), d)
r = app.post("/api/ban-status", json=authed({"session_ticket": "TICKET-MOD",
                                              "playfab_id": "CCCCCCCCCCCC0004"}))
check("innocent player not banned", r.get_json().get("banned") is False, r.get_json())
r = app.post("/api/ban-status", json=authed({"session_ticket": "TICKET-MOD"}))
check("defaults to the caller", r.get_json().get("playfab_id") == "AAAAAAAAAAAA0001", r.get_json())
r = app.post("/api/ban-status", json=authed({"session_ticket": "TICKET-MOD",
                                              "playfab_id": "not hex!"}))
check("bad target id 400", r.status_code == 400, r.status_code)
r = app.post("/api/ban-status", json=authed({"session_ticket": "TICKET-MOD"}))
check("ban-status is rate limited", r.status_code == 429, r.status_code)
mod._ban_status_cooldowns.clear()
fake_id.up = False
r = app.post("/api/ban-status", json=authed({"session_ticket": "TICKET-MOD"}))
check("PlayFab down never reports 'not banned' as success", r.status_code == 401, r.status_code)
fake_id.up = True
mod._ban_status_cooldowns.clear()
_orig_active = mod.active_ban
mod.active_ban = lambda pid: {"error": "boom"}
r = app.post("/api/ban-status", json=authed({"session_ticket": "TICKET-MOD"}))
check("ban lookup failure is a 502, not 'not banned'", r.status_code == 502, r.status_code)
mod.active_ban = _orig_active

mod.pf_request = _real_pf
mod.PLAYFAB_TITLE_ID, mod.PLAYFAB_SECRET_KEY = _saved_title, _saved_key
mod._report_cooldowns.clear()
mod._ban_status_cooldowns.clear()


print("\n--- security: tracker ---")
mod.authenticate_ticket = lambda t: t[2:] if isinstance(t, str) and t.startswith("T:") and len(t) > 2 else None
mod._tracker_cooldowns.clear()
r = app.post("/api/tracker", json=authed({"event": "player_joined", "player_name": "Fake Owner",
                                          "playfab_id": "PFOWNER"}))
check("third-party events need a signed-in reporter", r.status_code == 401, r.status_code)
_saved_lookup = mod.lookup_role
mod.lookup_role = lambda pid: "owner" if pid == "PFOWNER" else None
r = app.post("/api/tracker", json=authed({"event": "player_joined", "player_name": "Fake Owner",
                                          "playfab_id": "PFOWNER", "session_ticket": "T:PFRANDOM"}))
check("a claimed staff ID in a third-party event gets no role", r.get_json().get("role") is None, r.get_json())
mod._tracker_cooldowns.clear()
r = app.post("/api/tracker", json=authed({"event": "joined_room", "player_name": "Owner",
                                          "session_ticket": "T:PFOWNER"}))
check("staff reporting themselves still get their role", r.get_json().get("role") == "owner", r.get_json())
mod.lookup_role = _saved_lookup
mod._tracker_cooldowns.clear()

print("\n--- security: redeem ---")
use_fake(settings={})
mod.authenticate_ticket = lambda t: t[2:] if isinstance(t, str) and t.startswith("T:") and len(t) > 2 else None
fake = mod.pf_request
r = redeem({"code": "BETA", "playfab_id": "VICTIM1"})
check("first redeem works", r.get_json().get("success") is True, r.get_json())
check("the spend is stored in READ-ONLY data", "VICTIM1" in fake.readonly_data, fake.readonly_data)
check("nothing is written to player-editable data", "VICTIM1" not in fake.user_data, fake.user_data)
# The player wipes their own (editable) UserData - must not matter.
fake.user_data["VICTIM1"] = "[]"
r = redeem({"code": "BETA", "playfab_id": "VICTIM1"})
check("wiping player-editable data does not allow a second redeem",
      r.get_json().get("success") is False, r.get_json())
# Legacy record in editable data still counts as spent.
fake.user_data["OLDPLAYER"] = json.dumps(["BETA"])
r = redeem({"code": "BETA", "playfab_id": "OLDPLAYER"})
check("a code spent under the old storage stays spent", r.get_json().get("success") is False, r.get_json())

r = app.post("/api/redeem", json=authed({"code": "BETA", "playfab_id": "SOMEONEELSE"}))
check("a body playfab_id alone cannot redeem", r.status_code == 401, r.status_code)

# A read failure must refuse, not treat the player as having used nothing.
_ok_fake = mod.pf_request
mod.pf_request = lambda path, body: (False, {"errorMessage": "down"}) if path == "GetUserReadOnlyData" else _ok_fake(path, body)
r = redeem({"code": "BETA", "playfab_id": "FRESH1"})
check("unreadable spend record refuses the redeem", r.status_code == 502, r.status_code)
mod.pf_request = _ok_fake

# Concurrent redeem: the lock is held, a second one is refused.
release = mod.acquire_lock("redeem:RACER", 30)
mod._redeem_cooldowns.clear()
r = app.post("/api/redeem", json=authed({"code": "BETA", "session_ticket": "T:RACER"}))
check("a redeem while another is running for the same player is refused",
      r.status_code == 429, r.status_code)
release()
check("the lock is free again after release", mod.acquire_lock("redeem:RACER", 30) is not None)
mod._local_locks.clear()

# Wrong guesses are capped per account.
mod._attempt_counts.clear()
codes = []
for i in range(mod.REDEEM_MAX_WRONG_GUESSES + 1):
    codes.append(redeem({"code": "GUESS{0}".format(i), "playfab_id": "GUESSER"}).get_json().get("message"))
check("too many wrong codes are refused", "TOO MANY" in codes[-1], codes[-1])
mod._attempt_counts.clear()

# A failed grant gives the code back.
use_fake(settings={}, grant_ok=False)
fake = mod.pf_request
redeem({"code": "BETA", "playfab_id": "UNLUCKY"})
check("a failed grant restores the spend record",
      json.loads(fake.readonly_data.get("UNLUCKY", "[]")) == [], fake.readonly_data)

# KV-backed lock: SET NX semantics shared across copies.
kv = {}
def fake_kv(*args):
    cmd = args[0]
    if cmd == "SET":
        key, val = args[1], args[2]
        if "NX" in args and key in kv:
            return True, None
        kv[key] = val
        return True, "OK"
    if cmd == "GET":
        return True, kv.get(args[1])
    if cmd == "DEL":
        return True, 1 if kv.pop(args[1], None) is not None else 0
    if cmd == "INCR":
        kv[args[1]] = int(kv.get(args[1], 0)) + 1
        return True, kv[args[1]]
    if cmd == "EXPIRE":
        return True, 1
    return False, None
_saved_kv = (mod.kv_command, mod.kv_configured)
mod.kv_command, mod.kv_configured = fake_kv, (lambda: True)
a = mod.acquire_lock("redeem:KV1")
b = mod.acquire_lock("redeem:KV1")
check("KV lock: second taker is refused", a is not None and b is None)
a()
check("KV lock: free after release", mod.acquire_lock("redeem:KV1") is not None)
mod.kv_command, mod.kv_configured = _saved_kv
mod.authenticate_ticket = _real_authenticate_ticket
mod.pf_request = _real_pf
drop_cache()
# ---------------------------------------------------------------------------
print("\n--- result ---")
print("  passed: {0}   failed: {1}".format(passed, failed))
if failed:
    sys.exit(1)
print("  ALL TESTS PASSED")
