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

SECRET = "test-secret-123"

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
check("root lists 4 features", sorted(d.get("features") or []) == ["dashboard", "instaban", "reports", "tracker"], d)
check("root lists /api/report", "/api/report" in (d.get("endpoints") or []), d)
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
        "playfab_id": "PFALICE2", "player_count": 3, "max_players": 10,
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
check("different room bypasses cooldown", r.status_code == 200, r.status_code)

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
    "event": "joined_room", "player_name": "Mal", "playfab_id": "PFMAL",
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

r = app.get("/api/tracker/tracked", headers={"X-Api-Secret": SECRET})
check("tracked accepts the header secret", r.status_code == 200, r.status_code)
check("tracked returns 4 keys",
      sorted(k for k in r.get_json() if k != "success") == ["admins", "content_creators", "moderators", "owners"],
      r.get_json())

r = app.get("/api/tracker/tracked", headers={"X-Api-Secret": "wrong"})
check("tracked rejects a bad header secret", r.status_code == 401, r.status_code)

r = app.post("/api/tracker/refresh", json=authed({}))
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
r = app.get("/api/dashboard", headers={"X-Api-Secret": SECRET})
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
d = app.get("/api/dashboard", headers={"X-Api-Secret": SECRET}).get_json()
check("re-touch updates the name in place", d.get("player_count") == 2, d)
check("re-touch uses the newest name",
      "AliceRenamed" in {p["display_name"] for p in d["players"]}, d["players"])

# Regression: a fresh global count used to blank the player list entirely,
# and because the client refreshes that count every 15s against a 90s TTL it
# blanked on nearly every request.
mod._online_global_at = time.time()
mod._online_global_count = 5
d = app.get("/api/dashboard", headers={"X-Api-Secret": SECRET}).get_json()
check("fresh global count keeps the player list", len(d.get("players") or []) == 2, d)
check("fresh global count is the source", d.get("source") == "global_count", d)
check("headline prefers the higher count", d.get("online") == 5, d)

mod._online_global_count = 1
d = app.get("/api/dashboard", headers={"X-Api-Secret": SECRET}).get_json()
check("headline never under-reports the registry", d.get("online") == 2, d)

# clear the global count again so later /api/online tests exercise the registry
mod._online_global_at = 0
mod._online_global_count = 0

# a later event with a better name should update, not duplicate
mod.touch_online("AABBCCDDEEFF00112233445566778899", "AliceRenamed")
d = app.get("/api/dashboard", headers={"X-Api-Secret": SECRET}).get_json()
check("re-touch updates the name in place", d.get("player_count") == 2, d)
check("re-touch uses the newest name",
      "AliceRenamed" in {p["display_name"] for p in d["players"]}, d["players"])

# ---------------------------------------------------------------------------
print("\n--- privacy: playfab ids must not leak unauthenticated ---")
r = app.get("/api/online")
check("online 200 without a secret", r.status_code == 200, r.status_code)
check("online withholds the player list", "players" not in r.get_json(), r.get_json())
check("online still returns a count", isinstance(r.get_json().get("online"), int), r.get_json())

r = app.get("/api/online", headers={"X-Api-Secret": SECRET})
# snapshot is sorted by id, so '9' sorts before 'A'
check("online reveals the sorted id list to a valid secret",
      r.get_json().get("players") == ["99887766554433221100FFEEDDCCBBAA",
                                      "AABBCCDDEEFF00112233445566778899"],
      r.get_json())

r = app.get("/api/tracker/tracked")
check("rosters withheld without a secret", r.status_code == 401, r.status_code)

# secret must not be accepted from the query string (it would land in logs)
r = app.get("/api/dashboard?secret=" + SECRET)
check("query-string secret is not accepted", r.status_code == 401, r.status_code)

# ---------------------------------------------------------------------------
print("\n--- online registry ---")
r = app.post("/api/online-count", json=authed({"count": 42}))
check("online-count 200", r.status_code == 200, r.status_code)
check("online-count echoes", r.get_json().get("online") == 42, r.get_json())

r = app.get("/api/online")
check("online returns 200", r.status_code == 200, r.status_code)
check("online reads global count", r.get_json().get("online") == 42, r.get_json())
check("online source is global_count", r.get_json().get("source") == "global_count", r.get_json())

r = app.post("/api/online-count", json=authed({"count": "banana"}))
check("non-int count coerced to 0", r.get_json().get("online") == 0, r.get_json())

r = app.post("/api/online-count", json=authed({"count": -5}))
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
def redeem(payload):
    mod._redeem_cooldowns.clear()
    return app.post("/api/redeem", json=authed(payload))


check("code table: string shorthand becomes a cosmetic",
      mod._normalise_code_table({"BETA": "LBAAA"}).get("BETA", {}).get("reward_id") == "LBAAA",
      mod._normalise_code_table({"BETA": "LBAAA"}))

check("code table: keys are upper-cased",
      "BETA" in mod._normalise_code_table({"bEtA": "LBAAA"}),
      list(mod._normalise_code_table({"bEtA": "LBAAA"}).keys()))

check("code table: label falls back to the item id",
      mod._normalise_code_table({"BETA": {"reward_id": "LBAAA"}})["BETA"]["reward_label"] == "LBAAA")

check("code table: no reward id and no credits disables the code",
      mod._normalise_code_table({"BETA": {"reward_label": "nothing"}})["BETA"]["enabled"] is False)

check("code table: credits alone keeps the code enabled",
      mod._normalise_code_table({"BETA": {"credits": 500}})["BETA"]["enabled"] is True)

check("code table: unknown reward_type falls back to cosmetic",
      mod._normalise_code_table({"BETA": {"reward_type": "gold", "reward_id": "L"}})["BETA"]["reward_type"] == "cosmetic")

check("code table: malformed json yields an empty table",
      mod._normalise_code_table("{not json") == {})

check("code table: non-dict entry is skipped, not fatal",
      mod._normalise_code_table({"BETA": 7, "GAMMA": "LBAAA"}).get("GAMMA", {}).get("reward_id") == "LBAAA")

r = app.post("/api/redeem", json={"secret": "wrong", "code": "BETA", "playfab_id": "PF1"})
check("redeem rejects a bad secret", r.status_code == 401, r.status_code)

r = redeem({"code": "", "playfab_id": "PF1"})
check("redeem rejects an empty code", r.status_code == 400, r.status_code)

r = redeem({"code": "BETA", "playfab_id": ""})
check("redeem rejects a missing playfab id", r.status_code == 400, r.status_code)
check("redeem tells the player to sign in",
      "SIGN IN" in (r.get_json().get("message") or ""), r.get_json())

r = redeem({"code": "DOESNOTEXIST", "playfab_id": "PF1"})
check("redeem rejects an unknown code", r.get_json().get("success") is False, r.get_json())
check("redeem reports an unknown code in the message",
      "NOT RECOGNISED" in (r.get_json().get("message") or ""), r.get_json())


# --- fake PlayFab, so the grant path is exercised end to end ---------------
class _FakePlayFab(object):
    def __init__(self, codes, grant_ok=True):
        self.codes = dict(codes)
        self.grant_ok = grant_ok
        self.user_data = {}
        self.grants = []

    def __call__(self, path, body):
        if path == "GetTitleData":
            return True, {"data": {"Data": {"RedeemCodes": json.dumps(self.codes)}}}
        if path == "SetTitleData":
            self.codes = json.loads(body["Value"])
            return True, {}
        if path == "GetUserData":
            value = self.user_data.get(body["PlayFabId"])
            return True, {"data": {"Data": {"RedeemUsed": value} if value else {}}}
        if path == "UpdateUserData":
            self.user_data[body["PlayFabId"]] = body["Data"]["RedeemUsed"]
            return True, {}
        if path == "GrantCatalogItem":
            if not self.grant_ok:
                return False, {"errorMessage": "Entity not found"}
            self.grants.append((body["PlayFabId"], body["ItemId"]))
            return True, {}
        return False, {"errorMessage": "unexpected call " + str(path)}


_real_pf = mod.pf_request
_real_webhook = mod.REDEEM_WEBHOOK_URL
mod.REDEEM_WEBHOOK_URL = ""


def use_fake(codes, grant_ok=True):
    """Swap in a fake PlayFab and drop the cached code table.

    The 30s code-table cache is deliberate (it stops every redeem hammering
    TitleData), so a test that changes the table has to invalidate it too.
    """
    fake = _FakePlayFab(codes, grant_ok=grant_ok)
    mod.pf_request = fake
    mod._redeem_codes_cache = None
    mod._redeem_codes_cache_at = 0.0
    return fake


fake = use_fake({"BETA": {"reward_id": "LBAAA", "reward_label": "Beta Tester"}})

r = redeem({"code": "beta", "playfab_id": "PF1"})
d = r.get_json()
check("redeem accepts a lowercase code", d.get("success") is True, d)
check("redeem reports the reward label", d.get("reward_label") == "Beta Tester", d)
check("redeem reports the reward id", d.get("reward_id") == "LBAAA", d)
check("redeem granted the catalog item", fake.grants == [("PF1", "LBAAA")], fake.grants)

r = redeem({"code": "BETA", "playfab_id": "PF1"})
check("redeem blocks a second use of the same code",
      "ALREADY" in (r.get_json().get("message") or ""), r.get_json())
check("a repeat attempt does not grant again", len(fake.grants) == 1, fake.grants)

r = redeem({"code": "BETA", "playfab_id": "PF2"})
check("another player can still redeem the same code", r.get_json().get("success") is True, r.get_json())

# --- a failed grant must not burn the code -------------------------------
broken = use_fake({"BETA": {"reward_id": "LBAAA"}}, grant_ok=False)
r = redeem({"code": "BETA", "playfab_id": "PF3"})
check("a failed grant returns 502", r.status_code == 502, r.status_code)
check("a failed grant surfaces the PlayFab error",
      r.get_json().get("error") == "Entity not found", r.get_json())
check("a failed grant does not mark the code used", "PF3" not in broken.user_data, broken.user_data)

use_fake({"BETA": {"reward_id": "LBAAA"}})
r = redeem({"code": "BETA", "playfab_id": "PF3"})
check("the same code works after the failure clears", r.get_json().get("success") is True, r.get_json())

# --- max_uses -------------------------------------------------------------
# --- max_uses is per player ----------------------------------------------
limited = use_fake({"TWICE": {"reward_id": "LBAAA", "max_uses": 2}})
check("max_uses allows the first claim", redeem({"code": "TWICE", "playfab_id": "PFA"}).get_json().get("success") is True)
check("max_uses allows the second claim", redeem({"code": "TWICE", "playfab_id": "PFA"}).get_json().get("success") is True)
third = redeem({"code": "TWICE", "playfab_id": "PFA"}).get_json()
check("max_uses stops a third claim",
      third.get("success") is False and "ALREADY" in (third.get("message") or ""), third)
check("max_uses granted exactly twice", len(limited.grants) == 2, limited.grants)
check("max_uses does not affect other players",
      redeem({"code": "TWICE", "playfab_id": "PFB"}).get_json().get("success") is True)

# --- default is strictly one reward per player ---------------------------
once = use_fake({"ONCE": {"reward_id": "LBAAA"}})
check("default code: first claim succeeds", redeem({"code": "ONCE", "playfab_id": "PFA"}).get_json().get("success") is True)
again = redeem({"code": "ONCE", "playfab_id": "PFA"}).get_json()
check("default code: second claim is refused",
      again.get("success") is False and "ALREADY" in (again.get("message") or ""), again)
check("default code: granted exactly once", len(once.grants) == 1, once.grants)

# --- admin code management ------------------------------------------------
mod.pf_request = use_fake({})
r = app.post("/api/redeem-codes", json=authed({"code": "gama", "reward_id": "LFG1", "reward_label": "Gamer"}))
check("upsert creates a code", r.get_json().get("success") is True, r.get_json())
check("upsert upper-cases the code", "GAMA" in r.get_json().get("codes", {}), r.get_json())

r = app.post("/api/redeem-codes", json=authed({"code": "GAMA", "reward_label": "Gamer 2"}))
check("upsert merges without dropping the item id",
      r.get_json()["codes"]["GAMA"]["reward_id"] == "LFG1", r.get_json())
check("upsert updates the label",
      r.get_json()["codes"]["GAMA"]["reward_label"] == "Gamer 2", r.get_json())

r = app.post("/api/redeem-codes", json=authed({"code": "EMPTY", "reward_label": "nothing"}))
check("upsert refuses a code with no reward", r.status_code == 400, r.status_code)

check("list rejects a missing secret", app.get("/api/redeem-codes").status_code == 401)
r = app.get("/api/redeem-codes", headers={"X-Api-Secret": SECRET})
check("list returns the table", r.get_json().get("success") is True, r.get_json())

r = app.post("/api/redeem-codes", json=authed({"code": "GAMA", "delete": True}))
check("delete removes the code", "GAMA" not in r.get_json().get("codes", {}), r.get_json())

r = app.post("/api/redeem-codes", json=authed({"code": "GAMA", "delete": True}))
check("deleting an unknown code 404s", r.status_code == 404, r.status_code)

r = app.post("/api/redeem-codes", json={"secret": "wrong", "code": "X"})
check("upsert rejects a bad secret", r.status_code == 401, r.status_code)

mod.REDEEM_CODES_MAX_BYTES = 10
r = app.post("/api/redeem-codes", json=authed({"code": "BIG", "reward_id": "L" * 500}))
check("an oversized code table is refused", r.status_code == 502, r.status_code)
mod.REDEEM_CODES_MAX_BYTES = 3800

mod.pf_request = _real_pf
mod.REDEEM_WEBHOOK_URL = _real_webhook
mod._redeem_cooldowns.clear()

# ---------------------------------------------------------------------------
print("\n--- result ---")
print("  passed: {0}   failed: {1}".format(passed, failed))
if failed:
    sys.exit(1)
print("  ALL TESTS PASSED")
