"""
Superior Tag Discord bot - the "Online" half.

Keeps a live gateway connection so the bot shows as Online with
"Watching N monkes", receives every slash command / button over that
connection, and forwards it to the Vercel backend (/api/discord/relay),
which runs the actual command. Replies go straight back to Discord.

IMPORTANT: in the Discord Developer Portal, the "Interactions Endpoint URL"
must be EMPTY, otherwise Discord sends commands to Vercel instead of here.

Run:   start_bot.bat        (Windows, installs what it needs)
  or:  pip install -r bot/requirements.txt && python bot/gateway_bot.py

Settings (env vars, or lines NAME=value in private/vercel-env-values.txt):
  DISCORD_BOT_TOKEN   the bot token
  ADMIN_SECRET        same value as on Vercel (authorises the relay)
  BACKEND_URL         default https://superiortagaltbackend.vercel.app
"""
import asyncio
import json
import os
import sys
import time

import aiohttp
import discord

HERE = os.path.dirname(os.path.abspath(__file__))
PRIVATE_VALUES = os.path.join(HERE, "..", "private", "vercel-env-values.txt")
API = "https://discord.com/api/v10"
STAFF_COMMANDS = {"player", "ban", "unban", "code", "live", "verifybadge"}
INLINE_SECONDS = 2.2          # Discord allows 3s for the first reply
PRESENCE_EVERY = 60          # refresh numbers from the backend
ROTATE_EVERY = 15            # switch to the next status


def _looks_real(v):
    return bool(v) and "..." not in v and " " not in v and not v.lower().startswith("your")


def setting(name, default=""):
    v = os.environ.get(name, "").strip()
    if _looks_real(v):
        return v
    try:
        with open(PRIVATE_VALUES, encoding="utf-8") as fh:
            for line in fh:
                k, sep, val = line.partition("=")
                if sep and k.strip() == name:
                    val = val.strip().strip('"').strip("'")
                    if _looks_real(val):
                        return val
    except OSError:
        pass
    return default


TOKEN = setting("DISCORD_BOT_TOKEN")
RELAY_KEY = setting("ADMIN_SECRET")
BACKEND = setting("BACKEND_URL", "https://superiortagaltbackend.vercel.app").rstrip("/")


class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.none(), enable_debug_events=True)
        self.http_session = None

    async def setup_hook(self):
        self.http_session = aiohttp.ClientSession(headers={
            "User-Agent": "DiscordBot (https://github.com/ChrouserLLC/SuperiorTagAltBackend, 1.0)"})
        self.loop.create_task(self.presence_loop())
        # Render web services need something listening on $PORT.
        if os.environ.get("PORT"):
            from aiohttp import web
            app = web.Application()
            app.router.add_get("/", lambda r: web.Response(text="ok"))
            runner = web.AppRunner(app)
            await runner.setup()
            await web.TCPSite(runner, "0.0.0.0", int(os.environ["PORT"])).start()

    async def close(self):
        if self.http_session:
            await self.http_session.close()
        await super().close()

    async def on_ready(self):
        print("[bot] online as {0} - relaying to {1}".format(self.user, BACKEND))

    # -- presence ---------------------------------------------------------
    async def fetch_stats(self):
        """Live numbers from the backend, or None if it can't be reached."""
        try:
            async with self.http_session.get(BACKEND + "/api/discord/relay/presence",
                                             headers={"X-Relay-Key": RELAY_KEY},
                                             timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    return await r.json()
                if r.status == 401:
                    print("[bot] backend refused ADMIN_SECRET - check it matches Vercel")
        except Exception as e:
            print("[bot] stats check failed:", type(e).__name__)
        return None

    @staticmethod
    def rotation(stats):
        """(activity, status) pairs to cycle through, built from the live numbers."""
        W, P, L, C = (discord.ActivityType.watching, discord.ActivityType.playing,
                      discord.ActivityType.listening, discord.ActivityType.competing)
        if stats is None:
            # Backend down: red dot so staff notice.
            return [(discord.CustomActivity(name="\u26a0\ufe0f Backend unreachable"), discord.Status.dnd),
                    (discord.Activity(type=P, name="Superior Tag"), discord.Status.dnd)]
        count, rooms = stats.get("count"), stats.get("rooms") or 0
        if count is None:
            # Up, but no game is reporting: yellow moon.
            return [(discord.CustomActivity(name="\U0001f4a4 Waiting for monkes..."), discord.Status.idle),
                    (discord.Activity(type=P, name="Superior Tag on Quest"), discord.Status.idle),
                    (discord.Activity(type=L, name="/players \u2022 /status"), discord.Status.idle)]
        on = discord.Status.online
        items = [
            (discord.CustomActivity(name="\U0001f98d {0} monke{1} online".format(count, "" if count == 1 else "s")), on),
            (discord.Activity(type=W, name="{0} public room{1}".format(rooms, "" if rooms == 1 else "s")), on),
            (discord.Activity(type=P, name="Superior Tag on Quest"), on),
        ]
        if stats.get("top_mode"):
            items.append((discord.Activity(type=C, name=str(stats["top_mode"])), on))
        if stats.get("peak"):
            items.append((discord.CustomActivity(name="\U0001f4c8 Peak {0} this hour".format(stats["peak"])), on))
        items.append((discord.Activity(type=L, name="/players \u2022 /rooms \u2022 /status"), on))
        return items

    async def presence_loop(self):
        await self.wait_until_ready()
        stats, fetched_at, i = None, 0.0, 0
        while not self.is_closed():
            if time.time() - fetched_at >= PRESENCE_EVERY:
                stats, fetched_at = await self.fetch_stats(), time.time()
            items = self.rotation(stats)
            activity, status = items[i % len(items)]
            i += 1
            try:
                await self.change_presence(status=status, activity=activity)
            except Exception:
                pass
            await asyncio.sleep(ROTATE_EVERY)

    # -- interactions -----------------------------------------------------
    async def on_socket_raw_receive(self, msg):
        if '"INTERACTION_CREATE"' not in msg:
            return
        try:
            event = json.loads(msg)
        except ValueError:
            return
        if event.get("t") == "INTERACTION_CREATE":
            self.loop.create_task(self.handle(event.get("d") or {}))

    async def relay(self, payload):
        async with self.http_session.post(BACKEND + "/api/discord/relay", json=payload,
                                          headers={"X-Relay-Key": RELAY_KEY},
                                          timeout=aiohttp.ClientTimeout(total=55)) as r:
            if r.status == 401:
                raise RuntimeError("backend refused ADMIN_SECRET")
            if r.status >= 400:
                raise RuntimeError("backend HTTP {0}".format(r.status))
            return await r.json()

    async def discord(self, method, path, body):
        async with self.http_session.request(method, API + path, json=body,
                                             timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status >= 400:
                print("[bot] Discord {0} {1} -> {2}: {3}".format(method, path.split("/")[1], r.status,
                                                               (await r.text())[:200]))
            return r.status < 400

    async def handle(self, it):
        kind = it.get("type")
        if kind not in (2, 3):
            return
        iid, token, app_id = it.get("id"), it.get("token"), it.get("application_id")
        callback = "/interactions/{0}/{1}/callback".format(iid, token)
        name = (it.get("data") or {}).get("name")

        task = self.loop.create_task(self.relay(it))
        try:
            out = await asyncio.wait_for(asyncio.shield(task), INLINE_SECONDS)
            await self.discord("POST", callback, out)
            return
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            print("[bot] relay failed:", e)
            await self.discord("POST", callback, {"type": 4, "data": {
                "content": "The backend didn't answer - try again in a moment.", "flags": 64}})
            return

        # Too slow for 3s: say "thinking..." and fill the answer in after.
        deferred = {"type": 6} if kind == 3 else {"type": 5}
        if kind == 2 and name in STAFF_COMMANDS:
            deferred["data"] = {"flags": 64}
        await self.discord("POST", callback, deferred)
        hook = "/webhooks/{0}/{1}".format(app_id, token)
        try:
            out = await task
        except Exception as e:
            print("[bot] relay failed:", e)
            out = {"type": 4, "data": {"content": "The backend didn't answer - try again.", "flags": 64}}
        data = dict(out.get("data") or {})
        if kind == 3 and out.get("type") != 7:
            data["flags"] = 64
            await self.discord("POST", hook, data)
        else:
            data.pop("flags", None)
            await self.discord("PATCH", hook + "/messages/@original", data)


def main():
    if not TOKEN or not RELAY_KEY:
        print("Missing DISCORD_BOT_TOKEN or ADMIN_SECRET. Put them in private/vercel-env-values.txt "
              "(NAME=value lines) or set them as environment variables.")
        return 1
    Bot().run(TOKEN)
    return 0


if __name__ == "__main__":
    sys.exit(main())
