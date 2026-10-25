"""Tests for in-game staff actions (api/staff_actions.py). Run: python test_staff.py"""
import importlib.util, os, sys
os.environ.setdefault("API_SECRET", "s")
for k in ("PLAYFAB_TITLE_ID", "PLAYFAB_SECRET_KEY", "KV_REST_API_URL", "KV_REST_API_TOKEN", "REPORT_WEBHOOK_URL"):
    os.environ[k] = ""
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("alt_staff", os.path.join(HERE, "api", "index.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
app = mod.app.test_client()
passed = failed = 0
def check(n, c, e=""):
    global passed, failed
    print(("  PASS  " if c else "  FAIL  ") + n + ("" if c else "  -> " + str(e)))
    passed += bool(c); failed += (not c)
ROLES = {"MOD1": "moderator", "ADM1": "admin", "OWN1": "owner"}
mod.authenticate_ticket = lambda t: t[2:] if isinstance(t, str) and t.startswith("T:") else None
mod.lookup_role = lambda pid: ROLES.get(pid)
bans = []
mod.pf_request = lambda path, body: (bans.append(body) or (True, {})) if path == "BanUsers" else (True, {})
def post(path, ticket, **kw):
    kw.update({"secret": "s", "session_ticket": ticket})
    return app.post(path, json=kw)

r = post("/api/staff/role", "T:MOD1").get_json()
check("moderator is staff", r["is_staff"] and r["role"] == "moderator", r)
check("player is not staff", not post("/api/staff/role", "T:KID1").get_json()["is_staff"])
check("bad ticket refused", post("/api/staff/role", "nope").status_code == 401)
check("non-staff cannot act", post("/api/staff/action", "T:KID1", action="kick", target_id="KID2").status_code == 403)
r = post("/api/staff/action", "T:MOD1", action="kick", target_id="KID2").get_json()
aid = r.get("action_id")
check("moderator gets a kick action id", r["success"] and aid, r)
check("someone else can't redeem it", not post("/api/staff/verify", "T:KID3", action_id=aid).get_json()["valid"])
r = post("/api/staff/verify", "T:KID2", action_id=aid).get_json()
check("target redeems it", r["valid"] and r["action"] == "kick", r)
check("only once", not post("/api/staff/verify", "T:KID2", action_id=aid).get_json()["valid"])
check("fake id is invalid", not post("/api/staff/verify", "T:KID2", action_id="deadbeef").get_json()["valid"])
check("moderator can't touch an admin", post("/api/staff/action", "T:MOD1", action="freeze", target_id="ADM1").status_code == 403)
check("owner can act on an admin", post("/api/staff/action", "T:OWN1", action="freeze", target_id="ADM1").status_code == 200)
check("can't target yourself", post("/api/staff/action", "T:MOD1", action="fling", target_id="MOD1").status_code == 400)
check("unknown action refused", post("/api/staff/action", "T:MOD1", action="earrape", target_id="KID2").status_code == 400)
check("moderator perma-ban refused", post("/api/staff/action", "T:MOD1", action="ban", target_id="KID2", hours=0).status_code == 403)
r = post("/api/staff/action", "T:MOD1", action="ban", target_id="KID2", hours=24, reason="toxic")
check("moderator 24h ban goes to PlayFab", r.status_code == 200 and bans[-1]["Bans"][0]["DurationInHours"] == 24, r.get_json())
r = post("/api/staff/action", "T:ADM1", action="ban", target_id="KID2", hours=0)
check("admin can perma-ban", r.status_code == 200 and "DurationInHours" not in bans[-1]["Bans"][0])
print("\n  passed: {0}   failed: {1}".format(passed, failed))
sys.exit(1 if failed else 0)
