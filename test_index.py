"""Smoke tests for the merged Superior Tag Alt backend.

Covers tracker, reports and insta-ban in one run. Uses Flask's test client so
nothing leaves the machine and no PlayFab or Discord credentials are needed.

Run:  python test_index.py
"""

import importlib.util
import json
import os
import sys

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
check("root lists 3 features", sorted(d.get("features") or []) == ["instaban", "reports", "tracker"], d)
check("root lists /api/report", "/api/report" in (d.get("endpoints") or []), d)

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
check("tracked returns 200", r.status_code == 200, r.status_code)
check("tracked returns 4 keys",
      sorted(r.get_json().keys()) == ["admins", "content_creators", "moderators", "owners"],
      r.get_json())

r = app.post("/api/tracker/refresh", json=authed({}))
check("refresh 200", r.status_code == 200, r.status_code)
check("refresh success true", r.get_json().get("success") is True, r.get_json())

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

# ---------------------------------------------------------------------------
print("\n--- discord payload builders ---")
check("post_webhook with no url fails cleanly", mod.post_webhook("", {}) == (False, "unset"))
check("post_webhook with a URL missing its scheme fails cleanly, no raise",
      mod.post_webhook("not-a-url", {})[0] is False)
check("post_webhook with a non-http scheme fails cleanly, no raise",
      mod.post_webhook("ftp://example.invalid/x", {})[0] is False)

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
print("\n--- result ---")
print("  passed: {0}   failed: {1}".format(passed, failed))
if failed:
    sys.exit(1)
print("  ALL TESTS PASSED")
