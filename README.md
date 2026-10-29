# hzmods bot

Discord bot for the unofficial Horizon mod registry at [hzmods.lol](https://hzmods.lol). It is a separate program from `horizon-mods-web`, written with [disnake](https://github.com/DisnakeDev/disnake).

## What it does

- Gives role `1565177554216681552` to each new member.
- In channel `1565177345915232307`, a message from a person bans that person. The bot then deletes every message already in the channel and every message that arrives later. Bot and webhook authors are not banned. Their messages are still deleted.
- Slash commands `/mod`, `/recent`, `/user`, and `/site` read the public site API. Replies use Discord Components V2 through disnake. They are not classic embeds and they have no accent color. The commands are registered on the server that contains the closed channel when the bot starts.
- When a version is published, the bot posts one Components V2 message through the webhook in `.env`. Screenshots go in a media gallery and the short video goes in a file component, both as real attachments. The first start records versions that already exist and does not post them.

## Run

Python 3.11 or newer.

```bash
cd bot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python bot.py
```

Put the bot token and the webhook URL only in `.env`. `.env` and `data/` are gitignored.

In the Discord developer portal, turn on the Server Members privileged intent. The invite needs the bot and `applications.commands` scopes, plus Ban Members, Manage Roles, Manage Messages, Read Message History, and Send Messages. The bot's own role has to sit above the auto role.

`SITE_URL` is the site the bot reads. `https://hzmods.lol` is the default. For a machine on the same host, set it to that site's public URL, for example `http://127.0.0.1:8090`.

The bot polls `GET /api/v1/feed` every `POLL_SECONDS` (at least 15). It also listens on `127.0.0.1:8091` for `POST /notify` when `NOTIFY_SECRET` is set. The site can send that ping with `BOT_NOTIFY_URL` and `BOT_NOTIFY_SECRET`. Those two site variables are optional. Publishing still succeeds when the bot is down.

A webhook message can carry about 10 MB. Pictures on the site are capped at 4 MB and the clip at 8 MB. If a post would pass the webhook budget, the message keeps what fits and the mod page still has the rest.

Do not run slash commands in the closed channel. A command there is treated as a message in that channel.
