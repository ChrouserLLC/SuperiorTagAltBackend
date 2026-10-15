"""Seed the local dev backend with fake players so the dashboard has something
to render. Local use only - never run this against production.

Usage:  python seed_dev.py [base_url] [secret]
"""
import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5055"
SECRET = sys.argv[2] if len(sys.argv) > 2 else ""

PLAYERS = [
    ("AABBCCDDEEFF00112233445566778899", "Alice"),
    ("99887766554433221100FFEEDDCCBBAA", "Bob"),
    ("11223344556677889900112233445566", "Carol"),
    ("AABB1122334455667788990011223344", "Dave"),
    ("9988AABBCCDDEEFF0011223344556677", "Erin"),
    ("5566AABBCCDDEEFF0011223344556677", "Frank"),
    ("DDEEFF00112233445566778899AABBCC", "Grace"),
    ("FFEEDDCCBBAA99887766554433221100", "Heidi"),
]

names = [n for _, n in PLAYERS]


def post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, {}


for pid, name in PLAYERS:
    status, body = post("/api/tracker", {
        "secret": SECRET,
        "event": "player_joined",
        "room": "AB12CD",
        "player_name": name,
        "playfab_id": pid,
        "player_count": len(PLAYERS),
        "max_players": 10,
        "game_mode": "INFECTION_CITY_1",
        "scene": "GorillaTagSJR",
        "region": "USEast",
        "platform": "Quest3",
        "players": names,
    })
    print("  {0:<6} tracker -> {1} {2}".format(name, status, body.get("error", "")))

print("  done: {0} players sent to {1}".format(len(PLAYERS), BASE))
