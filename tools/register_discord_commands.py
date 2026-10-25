"""
Registers the bot's slash commands with Discord. Run once, and again after
changing a command's options:

    set DISCORD_APP_ID=...
    set DISCORD_BOT_TOKEN=...
    set DISCORD_GUILD_ID=...      (your server: commands appear instantly)
    python tools/register_discord_commands.py

Without DISCORD_GUILD_ID the commands are registered globally, which can take
up to an hour to show up.
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))

# discord_bot imports flask; it is only needed for the command list here.
import discord_bot  # noqa: E402


def main():
    app_id = os.environ.get("DISCORD_APP_ID", "").strip()
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    guild = os.environ.get("DISCORD_GUILD_ID", "").strip()
    if not app_id or not token:
        print("Set DISCORD_APP_ID and DISCORD_BOT_TOKEN first.")
        return 1

    path = ("/applications/{0}/guilds/{1}/commands".format(app_id, guild) if guild
            else "/applications/{0}/commands".format(app_id))
    req = urllib.request.Request(
        discord_bot.DISCORD_API + path,
        data=json.dumps(discord_bot.command_definitions()).encode("utf-8"),
        method="PUT",
        headers={"Authorization": "Bot " + token, "Content-Type": "application/json",
                 "User-Agent": "DiscordBot (https://github.com/ChrouserLLC/SuperiorTagAltBackend, 1.0)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            names = [c["name"] for c in json.loads(resp.read().decode("utf-8"))]
            print("Registered {0} commands{1}: {2}".format(
                len(names), " in your server" if guild else " globally", ", ".join(names)))
            return 0
    except urllib.error.HTTPError as e:
        print("Discord said HTTP {0}: {1}".format(e.code, e.read().decode("utf-8")))
        return 1


if __name__ == "__main__":
    sys.exit(main())
