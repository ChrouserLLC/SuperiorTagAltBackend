"""
In-game staff actions for the Superior menu (Unity: SuperiorMenu.cs).

    POST /api/staff/role     who am I? -> {"role": "moderator", "is_staff": true}
    POST /api/staff/action   staff asks to kick / freeze / fling / ban someone
    POST /api/staff/verify   the TARGET asks "is this action against me real?"

Nothing here trusts the game client. The caller is identified from their own
PlayFab session ticket and must be an owner, admin or moderator in the
TrackedPlayers title data. Kick/freeze/fling create a single-use action ID
that only the named target can redeem, so a modded client that sends a fake
Photon event can't make anyone else do anything. Bans go straight to PlayFab
and are then enforced by the existing ban-status check.

Every action is logged to REPORT_WEBHOOK_URL so staff are accountable.
"""
import json
import os
import threading
import time

from flask import jsonify, request

STAFF_ROLES = ("owner", "admin", "moderator")
RANK = {"owner": 3, "admin": 2, "moderator": 1}
ACTIONS = ("kick", "freeze", "fling", "ban")
ACTION_TTL_SECONDS = 120
MAX_BAN_HOURS = {"owner": 0, "admin": 0, "moderator": 72}   # 0 = no limit (permanent allowed)
ACTIONS_PER_MINUTE = 20

_mem_actions = {}
_mem_lock = threading.Lock()
_rate = {}


def _rate_ok(caller):
    now = time.time()
    with _mem_lock:
        hits = [t for t in _rate.get(caller, []) if now - t < 60]
        if len(hits) >= ACTIONS_PER_MINUTE:
            _rate[caller] = hits
            return False
        hits.append(now)
        _rate[caller] = hits
    return True


def _store(deps, action_id, record):
    if deps.kv_configured():
        ok, _ = deps.kv_command("SET", "staffact:" + action_id, json.dumps(record), "EX", ACTION_TTL_SECONDS)
        return ok
    with _mem_lock:
        _mem_actions[action_id] = record
    return True


def _take(deps, action_id, target):
    """Single use, and only the named target can use it up."""
    if deps.kv_configured():
        ok, raw = deps.kv_command("GET", "staffact:" + action_id)
        if not ok or not raw:
            return None
        try:
            record = json.loads(raw)
        except ValueError:
            return None
        if record.get("target") != target:
            return None
        ok, deleted = deps.kv_command("DEL", "staffact:" + action_id)
        return record if ok and deleted else None   # someone else got it first
    with _mem_lock:
        record = _mem_actions.get(action_id)
        if not record or record.get("target") != target:
            return None
        return _mem_actions.pop(action_id, None)


def _audit(deps, caller, role, action, target, extra):
    url = getattr(deps, "REPORT_WEBHOOK_URL", "") or os.environ.get("REPORT_WEBHOOK_URL", "")
    if not url:
        return
    fields = [{"name": "Staff", "value": "`{0}` ({1})".format(caller, role), "inline": True},
              {"name": "Target", "value": "`{0}`".format(target), "inline": True}]
    if extra:
        fields.append({"name": "Details", "value": extra[:900], "inline": False})
    try:
        deps.post_webhook(url, {"embeds": [{"title": "In-game staff action: " + action, "color": 0xA855F7,
                                             "fields": fields}]})
    except Exception:
        pass


def register(app, deps):
    def _caller(body):
        if not deps.check_secret(body):
            return None, (jsonify({"success": False, "error": "bad secret"}), 401)
        pid = deps.authenticate_ticket(body.get("session_ticket"))
        if pid is None:
            return None, (jsonify({"success": False, "error": "invalid session"}), 401)
        return pid, None

    @app.route("/api/staff/role", methods=["POST"])
    def staff_role():
        body = request.get_json(silent=True) or {}
        pid, err = _caller(body)
        if err:
            return err
        role = deps.lookup_role(pid)
        return jsonify({"success": True, "role": role or "", "is_staff": role in STAFF_ROLES})

    @app.route("/api/staff/action", methods=["POST"])
    def staff_action():
        body = request.get_json(silent=True) or {}
        pid, err = _caller(body)
        if err:
            return err
        role = deps.lookup_role(pid)
        if role not in STAFF_ROLES:
            return jsonify({"success": False, "error": "not staff"}), 403
        if not _rate_ok(pid):
            return jsonify({"success": False, "error": "slow down"}), 429

        action = str(body.get("action") or "").lower()
        target = str(body.get("target_id") or "").strip()
        if action not in ACTIONS:
            return jsonify({"success": False, "error": "unknown action"}), 400
        if not deps._PLAYFAB_ID_RE.match(target) or target == pid:
            return jsonify({"success": False, "error": "invalid target"}), 400
        target_role = deps.lookup_role(target)
        if target_role in STAFF_ROLES and RANK[role] <= RANK[target_role]:
            return jsonify({"success": False, "error": "target is staff"}), 403

        if action == "ban":
            try:
                hours = int(body.get("hours") or 0)
            except (TypeError, ValueError):
                hours = 0
            limit = MAX_BAN_HOURS[role]
            if hours < 0 or (limit and (hours == 0 or hours > limit)):
                return jsonify({"success": False, "error": "moderators can ban for at most {0}h".format(limit)}), 403
            reason = str(body.get("reason") or "Banned by staff in-game")[:120]
            ban = {"PlayFabId": target, "Reason": "[In-game] " + reason}
            if hours:
                ban["DurationInHours"] = hours
            ok, result = deps.pf_request("BanUsers", {"Bans": [ban]})
            if not ok:
                return jsonify({"success": False, "error": "PlayFab refused the ban"}), 502
            _audit(deps, pid, role, "ban", target, "{0} - {1}".format(
                "permanent" if not hours else "{0}h".format(hours), reason))
            return jsonify({"success": True, "action": "ban"})

        action_id = os.urandom(12).hex()
        record = {"target": target, "action": action, "by": pid, "role": role, "exp": time.time() + ACTION_TTL_SECONDS}
        if not _store(deps, action_id, record):
            return jsonify({"success": False, "error": "storage unavailable"}), 503
        _audit(deps, pid, role, action, target, "")
        return jsonify({"success": True, "action": action, "action_id": action_id})

    @app.route("/api/staff/verify", methods=["POST"])
    def staff_verify():
        body = request.get_json(silent=True) or {}
        pid, err = _caller(body)
        if err:
            return err
        action_id = str(body.get("action_id") or "")
        if not action_id or len(action_id) > 64:
            return jsonify({"success": True, "valid": False})
        record = _take(deps, action_id, pid)
        if not record or record.get("exp", 0) < time.time():
            return jsonify({"success": True, "valid": False})
        return jsonify({"success": True, "valid": True, "action": record["action"]})
