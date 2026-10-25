"""
Registers the bot's slash commands with Discord. Run once, and again after
changing a command's options:

    python tools/register_discord_commands.py

It reads DISCORD_APP_ID and DISCORD_BOT_TOKEN from private/vercel-env-values.txt
(or real environment variables) and asks for your server ID, so commands appear
in your server instantly.

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


PRIVATE_VALUES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "private", "vercel-env-values.txt")


def _looks_real(value):
    return bool(value) and "..." not in value and " " not in value and not value.lower().startswith("your")


def _from_private_file(name):
    """Reads NAME=value from private/vercel-env-values.txt (kept out of git)."""
    try:
        with open(PRIVATE_VALUES, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def _value(name, prompt=None):
    value = os.environ.get(name, "").strip()
    if not _looks_real(value):
        value = _from_private_file(name)
    if not _looks_real(value) and prompt:
        value = input(prompt).strip()
    return value if _looks_real(value) else ""


def main():
    app_id = _value("DISCORD_APP_ID")
    token = _value("DISCORD_BOT_TOKEN")
    guild = _value("DISCORD_GUILD_ID",
                   "Your Discord server ID (right-click the server icon > Copy Server ID; "
                   "blank = register globally): ")
    if not app_id or not token:
        print("Couldn't find DISCORD_APP_ID / DISCORD_BOT_TOKEN. Put them in private/vercel-env-values.txt "
              "or set them as real values (not '...').")
        return 1
    if guild and not guild.isdigit():
        print("That server ID doesn't look right - it should be only digits.")
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
