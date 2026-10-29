# AGENTS.md

Bot-only rules. The full guide for the site and this bot is `horizon-mods-web/AGENTS.md` in the sibling directory. Follow that file when both trees are present. Reply to the user in Russian. This file stays English.

## Git

This repo is `bot`, branch `main`, remote `https://github.com/quomy-code/horizon-mods-app.git`. When a change here is finished, commit it and push it. Do not commit `.env`, `data/`, `__pycache__`, or `.venv`. Do not change git config.

## Secrets

Never print `DISCORD_TOKEN`, `WEBHOOK_URL`, or `NOTIFY_SECRET`. Do not start the bot unless the user asks. Do not bind `2403` or `2521` from a tool. The live gitignored env listens on `0.0.0.0:2403`. The example file stays on `8091` unless the user asks to change it.

## Behavior

Python 3.11+, disnake. English strings only.

- Auto role `1565177554216681552` on join.
- Channel `1565177345915232307` is closed. A human message or slash command there bans that person and purges history (`limit=None`). Bot and webhook authors are not banned. Their messages are still deleted. `Guild.ban` uses `clean_history_duration=0`.
- `/mod`, `/recent`, `/user`, and `/site` are guild commands (`CommandSyncFlags.none()`). Intents are default plus members. `message_content` is not required.
- Announcements are Components V2, flag `32768`, no embeds, no accent color. Webhook execute uses `with_components=true`. Keep the edit monkeypatch. `allowed_mentions` parses nothing.
- The first feed poll records existing versions and does not post them.
- Publishing on the site must succeed when this bot is down.

Tests: `python3 -m unittest test_payload.py` from this directory.

Discord application URLs: `https://hzmods.lol/app/terms` and `https://hzmods.lol/app/privacy`.
