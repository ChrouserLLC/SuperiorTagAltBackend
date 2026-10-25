"""
Tests for the Discord bot (api/discord_bot.py). Run: python test_discord.py
Signs interactions with a throwaway Ed25519 key, exactly like Discord does.
"""
import importlib.util
import json
import os
import sys
import time

os.environ.setdefault("API_SECRET", "test-secret-123")
os.environ.setdefault("ADMIN_SECRET", "test-admin-456")
for k in ("PLAYFAB_TITLE_ID", "PLAYFAB_SECRET_KEY", "KV_REST_API_URL", "KV_REST_API_TOKEN",
          "REPORT_WEBHOOK_URL", "DISCORD_BOT_TOKEN", "DISCORD_REPORT_CHANNEL_ID"):
    os.environ[k] = ""

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

KEY = Ed25519PrivateKey.generate()
os.environ["DISCORD_PUBLIC_KEY"] = KEY.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
os.environ["DISCORD_STAFF_ROLE_IDS"] = "999"
os.environ["PUBLIC_BASE_URL"] = "https://backend.example"

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("alt_backend_d", os.path.join(HERE, "api", "index.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
bot = mod.discord_bot
app = mod.app.test_client()

passed = failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        print("  PASS  " + name)
        passed += 1
    else:
        print("  FAIL  " + name + ("  -> " + str(extra) if extra else ""))
        failed += 1


def interact(payload, sign=True, tamper=False):
    body = json.dumps(payload).encode("utf-8")
    ts = str(int(time.time()))
    sig = KEY.sign(ts.encode() + body).hex()
    if tamper:
        body = body.replace(b"players", b"PLAYERS")
    headers = {"X-Signature-Ed25519": sig, "X-Signature-Timestamp": ts} if sign else {}
    return app.post("/api/discord/interactions", data=body, headers=headers, content_type="application/json")


def command(name, options=None, staff=False):
    return {"type": 2, "data": {"name": name, "options": options or []},
            "member": {"roles": ["999"] if staff else ["1"], "user": {"id": "42", "username": "mod"}},
            "channel_id": "123"}


print("\n--- signature ---")
r = interact({"type": 1})
check("PING answers PONG", r.status_code == 200 and r.get_json() == {"type": 1}, r.get_data())
check("unsigned request refused", interact({"type": 1}, sign=False).status_code == 401)
check("tampered body refused", interact(command("players"), tamper=True).status_code == 401)

print("\n--- data from the game ---")
mod.authenticate_ticket = lambda t: t[2:] if isinstance(t, str) and t.startswith("T:") else None
for i, n in enumerate([4, 6, 9]):
    mod._tracker_cooldowns.clear()
    bot._mem["counts"][bot._minute() - (2 - i)] = n
r = app.post("/api/online-count", json={
    "secret": "test-secret-123", "session_ticket": "T:AAAAAAAAAAAA0001", "count": 10,
    "room": {"code": "ABCD", "players": 7, "max": 10, "mode": "forestINFECTION", "public": True},
    "players": [{"id": "BBBBBBBBBBBB0002", "name": "Monke"}, {"id": "not-an-id", "name": "x"}]})
check("online-count accepts the room report", r.status_code == 200, r.get_json())
check("current count stored", bot.current_count(mod._deps)["count"] == 10)
check("room stored", [x["code"] for x in bot.public_rooms(mod._deps)] == ["ABCD"])
check("last seen stored for valid ids only",
      bot.last_seen(mod._deps, "BBBBBBBBBBBB0002") and bot.last_seen(mod._deps, "not-an-id") is None)
mod._tracker_cooldowns.clear()
app.post("/api/online-count", json={
    "secret": "test-secret-123", "session_ticket": "T:AAAAAAAAAAAA0003", "count": 10,
    "room": {"code": "PRIV", "players": 3, "max": 10, "mode": "x", "public": False}})
check("private rooms are not listed", "PRIV" not in [x["code"] for x in bot.public_rooms(mod._deps)])

print("\n--- /players ---")
r = interact(command("players"))
d = r.get_json()
emb = d["data"]["embeds"][0]
check("/players replies with an embed", d["type"] == 4 and "10" in emb["description"], d)
check("/players shows the 1h peak", any(f["name"] == "Peak (1h)" and "10" in f["value"] for f in emb["fields"]), emb)
check("/players links the chart", emb["image"]["url"].startswith("https://backend.example/api/players/chart.png"), emb)
check("/players never pings anyone", d["data"]["allowed_mentions"] == {"parse": []})
r = app.get("/api/players/chart.png")
check("chart is a PNG", r.status_code == 200 and r.data[:8] == b"\x89PNG\r\n\x1a\n", r.status_code)

print("\n--- /rooms and /status ---")
d = interact(command("rooms")).get_json()
check("/rooms lists the public room", "ABCD" in d["data"]["embeds"][0]["description"], d)
bot.http_get_json = lambda url, timeout=2.0: (200, {"status": "HEALTHY", "success": True, "sessions": 3})
d = interact(command("status")).get_json()
desc = d["data"]["embeds"][0]["description"]
check("/status reports each service", "Attestation" in desc and "SisterShip" in desc and "PlayFab" in desc, desc)

print("\n--- staff gating ---")
for name in ("player", "ban", "unban", "code", "live"):
    d = interact(command(name, [{"name": "player", "type": 3, "value": "x"}])).get_json()
    check("/" + name + " refused for non-staff", "staff" in d["data"]["embeds"][0]["description"].lower(), d)


class FakePF(object):
    def __init__(self):
        self.bans = []
        self.revoked = []

    def __call__(self, path, body):
        if path == "BanUsers":
            self.bans.append(body["Bans"][0])
            return True, {"data": {"BanData": []}}
        if path == "RevokeAllBansForUser":
            self.revoked.append(body["PlayFabId"])
            return True, {"data": {}}
        if path == "GetUserAccountInfo":
            return True, {"data": {"UserInfo": {"TitleInfo": {"DisplayName": "MONKE1234",
                                                              "Created": "2026-01-02T03:04:05Z",
                                                              "LastLogin": "2026-10-20T00:00:00Z"}}}}
        if path == "GetUserBans":
            return True, {"data": {"BanData": []}}
        return False, {"errorMessage": "unexpected " + path}


fake = FakePF()
mod.pf_request = fake
mod.pf_admin_request = lambda path, body: (False, {"errorMessage": "nope"})
mod.lookup_role = lambda pid: "moderator" if pid == "CCCCCCCCCCCC0003" else None

print("\n--- /player /ban /unban ---")
d = interact(command("player", [{"name": "player", "type": 3, "value": "Monke"}], staff=True)).get_json()
emb = d["data"]["embeds"][0]
check("/player finds a recently seen name", "BBBBBBBBBBBB0002" in json.dumps(emb), emb)
check("/player is only visible to the caller", d["data"].get("flags") == 64)
check("/player shows last seen", any(f["name"] == "Last seen in a room" for f in emb["fields"]), emb)

d = interact(command("ban", [{"name": "player", "type": 3, "value": "BBBBBBBBBBBB0002"},
                             {"name": "hours", "type": 4, "value": 24},
                             {"name": "reason", "type": 3, "value": "cheating"}], staff=True)).get_json()
check("/ban bans through PlayFab", fake.bans and fake.bans[-1]["DurationInHours"] == 24
      and "cheating" in fake.bans[-1]["Reason"], fake.bans)
d = interact(command("ban", [{"name": "player", "type": 3, "value": "BBBBBBBBBBBB0002"},
                             {"name": "hours", "type": 4, "value": 0},
                             {"name": "reason", "type": 3, "value": "x"}], staff=True)).get_json()
check("/ban hours 0 is permanent", "DurationInHours" not in fake.bans[-1], fake.bans[-1])
d = interact(command("ban", [{"name": "player", "type": 3, "value": "CCCCCCCCCCCC0003"},
                             {"name": "hours", "type": 4, "value": 1},
                             {"name": "reason", "type": 3, "value": "x"}], staff=True)).get_json()
check("/ban refuses to ban staff", "staff" in d["data"]["embeds"][0]["description"], d)
interact(command("unban", [{"name": "player", "type": 3, "value": "BBBBBBBBBBBB0002"}], staff=True))
check("/unban revokes bans", fake.revoked == ["BBBBBBBBBBBB0002"], fake.revoked)
d = interact(command("player", [{"name": "player", "type": 3, "value": "nobody"}], staff=True)).get_json()
check("/player with an unknown name explains itself", "No player found" in d["data"]["embeds"][0]["description"])

print("\n--- /code ---")
calls = []
mod.upsert_code = lambda body: (calls.append(body) or ({"success": True, "code": body["code"],
                                                        "entry": {"reward_type": "currency", "reward_id": "SR",
                                                                  "amount": 500, "enabled": True}}, 200))
mod.list_codes = lambda: ({"GOLD": {"reward_type": "currency", "reward_id": "SR", "amount": 500}}, [])
sub = lambda name, opts: [{"type": 1, "name": name, "options": opts}]
d = interact(command("code", sub("list", []), staff=True)).get_json()
check("/code list shows codes", "GOLD" in d["data"]["embeds"][0]["description"], d)
interact(command("code", sub("create", [{"name": "code", "value": "gold"}, {"name": "type", "value": "currency"},
                                        {"name": "reward", "value": "sr"}, {"name": "amount", "value": 500}]),
                 staff=True))
check("/code create sends a currency code", calls[-1]["code"] == "GOLD" and calls[-1]["reward_id"] == "SR"
      and calls[-1]["amount"] == 500, calls[-1])
interact(command("code", sub("disable", [{"name": "code", "value": "GOLD"}]), staff=True))
check("/code disable turns it off", calls[-1] == {"code": "GOLD", "enabled": False}, calls[-1])
interact(command("code", sub("delete", [{"name": "code", "value": "GOLD"}]), staff=True))
check("/code delete deletes", calls[-1] == {"code": "GOLD", "delete": True}, calls[-1])

print("\n--- report buttons ---")
btn = {"type": 3, "data": {"custom_id": "rban:168:BBBBBBBBBBBB0002"},
       "member": {"roles": ["999"], "user": {"id": "42", "username": "mod"}},
       "message": {"embeds": [{"title": "Report", "description": "Toxicity"}]}}
d = interact(btn).get_json()
check("Ban 7d bans for 168h", fake.bans[-1]["DurationInHours"] == 168, fake.bans[-1])
check("the report message is updated and the buttons removed",
      d["type"] == 7 and d["data"]["components"] == [] and "Banned 168h" in d["data"]["embeds"][0]["footer"]["text"], d)
btn["member"]["roles"] = ["1"]
d = interact(btn).get_json()
check("non-staff cannot press report buttons", "staff" in d["data"]["embeds"][0]["description"].lower(), d)
check("buttons only for real PlayFab ids", bot.report_buttons("not an id") == [] and bot.report_buttons("AAAAAAAAAAAA0001"))

sent = []
ok, err = bot.post_report({"embeds": [{}]}, "AAAAAAAAAAAA0001", lambda p: (sent.append(p) or (True, None)))
check("without a bot channel, reports still go to the webhook", ok and sent, sent)

print("\n--- command definitions ---")
defs = bot.command_definitions()
check("every command is defined", sorted(c["name"] for c in defs) ==
      sorted(["players", "status", "rooms", "player", "ban", "unban", "code", "live"]))
check("staff commands are hidden by default",
      all(c.get("default_member_permissions") == "0" for c in defs if c["name"] in bot.STAFF_COMMANDS))

print("\n--- result ---")
print("  passed: {0}   failed: {1}".format(passed, failed))
sys.exit(1 if failed else 0)
