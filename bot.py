"""Discord bot for hzmods: auto role, closed channel, site commands, publish webhook."""

import asyncio
import hmac
import io
import json
import logging
import os
import re
import urllib.parse
from pathlib import Path

import aiohttp
import disnake
from aiohttp import web
from disnake.ext import commands
from disnake.http import Route
from disnake.webhook.async_ import AsyncWebhookAdapter, async_context

from components import container, link_button, link_row, media_gallery, separator, text_display
from payload import announcement, clip, pack_files, same_origin

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "data" / "state.json"
LOG = logging.getLogger("hzmods")

AUTO_ROLE_ID = 1565177554216681552
BAN_CHANNEL_ID = 1565177345915232307
SITE_URL = "https://hzmods.lol"
WEBHOOK_URL = ""
NOTIFY_HOST = "127.0.0.1"
NOTIFY_PORT = 8091
POLL_SECONDS = 45
MENTIONS = disnake.AllowedMentions.none()


def _install_webhook_component_edit():
    """Incoming webhooks drop components on edit unless with_components=true.

    disnake 2.12 sends that query on execute and leaves it off on edit.
    """

    def edit_webhook_message(
        self,
        webhook_id,
        token,
        message_id,
        *,
        session,
        payload=None,
        multipart=None,
        files=None,
        thread_id=None,
    ):
        params = {"with_components": "true"}
        if thread_id is not None:
            params["thread_id"] = thread_id
        route = Route(
            "PATCH",
            "/webhooks/{webhook_id}/{webhook_token}/messages/{message_id}",
            webhook_id=webhook_id,
            webhook_token=token,
            message_id=message_id,
        )
        return self.request(route, session, payload=payload, multipart=multipart, files=files, params=params)

    AsyncWebhookAdapter.edit_webhook_message = edit_webhook_message


_install_webhook_component_edit()


def load_env(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_state():
    if not STATE_PATH.exists():
        return {"seeded": False, "seen": [], "messages": {}}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"seeded": False, "seen": [], "messages": {}}
    data.setdefault("seeded", False)
    data.setdefault("seen", [])
    data.setdefault("messages", {})
    return data


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def secret_ok(header, secret):
    if not secret:
        return False
    left = header.encode()
    right = f"Bearer {secret}".encode()
    if len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


async def get_json(session, path):
    url = SITE_URL.rstrip("/") + path
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            if resp.status != 200:
                return None
            return await resp.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None


async def download(session, url):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                return None
            data = await resp.content.read(9_500_001)
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None
    if not data or len(data) > 9_500_000:
        return None
    return data


async def collect(session, item):
    downloaded = []
    missing = 0
    for row in item.get("media") or []:
        url = same_origin(SITE_URL, row.get("url") or "")
        if not url:
            missing += 1
            continue
        data = await download(session, url)
        downloaded.append({
            "kind": row.get("kind"),
            "ext": row.get("ext"),
            "caption": row.get("caption") or "",
            "data": data or b"",
        })
    packed, skipped = pack_files(downloaded)
    return packed, skipped + missing


def upload_files(rows, item):
    files = []
    for row in rows:
        description = clip(row.get("caption") or item.get("name"), 256)
        files.append(disnake.File(
            io.BytesIO(row["data"]),
            filename=row["name"],
            description=description or None,
        ))
    return files


def reply_mod(found, several=None):
    if several is not None:
        if not several:
            return container([text_display("No published mod matches that.")])
        lines = [f"**{row.get('name')}** `{row.get('id')}` — {row.get('summary') or ''}" for row in several[:8]]
        return container([
            text_display("Several mods match\n" + "\n".join(lines)),
            link_button("Catalog", same_origin(SITE_URL, "/mods")),
        ])
    versions = found.get("versions") or []
    latest = versions[0]["version"] if versions else "—"
    lines = [
        f"## {found.get('name')}",
        found.get("summary") or "",
        f"`{found.get('id')}` · {found.get('kind')} · {latest}",
        found.get("owner") or "",
    ]
    children = [text_display("\n".join(line for line in lines if line))]
    images = []
    has_video = False
    for item in found.get("media") or []:
        if item.get("kind") == "video":
            has_video = True
            continue
        url = same_origin(SITE_URL, item.get("url") or "")
        if url.startswith("https://"):
            images.append({"url": url, "description": item.get("caption") or found.get("name") or ""})
    if images:
        children.append(separator())
        children.append(media_gallery(images))
    if has_video:
        children.append(text_display("This page has a short video."))
    children.append(link_button("Open mod", same_origin(SITE_URL, f"/mods/{found.get('id')}")))
    return container(children)


def reply_recent(versions):
    if not versions:
        return container([text_display("No published versions yet.")])
    lines = [f"**{row.get('name')}** `{row.get('version')}` · {row.get('owner') or ''}" for row in versions[:5]]
    return container([
        text_display("Latest versions\n" + "\n".join(lines)),
        link_button("Catalog", same_origin(SITE_URL, "/mods")),
    ])


def reply_user(data):
    user = data.get("user") or {}
    stats = data.get("stats") or {}
    name = user.get("displayName") or user.get("username") or "profile"
    text = "\n".join([
        f"## {name}",
        f"@{user.get('username')}",
        f"Mods {stats.get('mods', 0)} · downloads {stats.get('downloads', 0)} · followers {stats.get('followers', 0)}",
    ])
    return container([
        text_display(text),
        link_button("Profile", same_origin(SITE_URL, f"/u/{user.get('username')}")),
    ])


def reply_site():
    root = SITE_URL.rstrip("/")
    return container([
        text_display("## hzmods\nUnofficial Horizon mod registry."),
        link_row([
            ("Site", root + "/"),
            ("Catalog", root + "/mods"),
            ("Index", root + "/api/v1/index.json"),
            ("Feed", root + "/api/v1/feed"),
            ("API", root + "/docs/api"),
        ]),
    ])


async def defer_v2(inter):
    adapter = async_context.get()
    await adapter.create_interaction_response(
        inter.id,
        inter.token,
        session=inter._session,
        type=disnake.InteractionResponseType.deferred_channel_message.value,
        data={"flags": disnake.MessageFlags.is_components_v2.flag},
    )
    inter.response._response_type = disnake.InteractionResponseType.deferred_channel_message


class HzBot(commands.InteractionBot):
    def __init__(self):
        intents = disnake.Intents.default()
        intents.members = True
        super().__init__(
            intents=intents,
            command_sync_flags=commands.CommandSyncFlags.none(),
            allowed_mentions=MENTIONS,
        )
        self.session = None
        self.state = load_state()
        self.lock = asyncio.Lock()
        self.purge_lock = asyncio.Lock()
        self._booted = False
        self._runner = None
        self._bind_commands()

    def _bind_commands(self):
        @self.slash_command(description="Look up a mod on hzmods")
        async def mod(inter, query: str = commands.Param(description="Mod id or part of the name")):
            await self.answer(inter, lambda: self.command_mod(query))

        @self.slash_command(description="Latest published versions")
        async def recent(inter):
            await self.answer(inter, self.command_recent)

        @self.slash_command(description="Public profile on hzmods")
        async def user(inter, name: str = commands.Param(description="Name from hzmods")):
            await self.answer(inter, lambda: self.command_user(name))

        @self.slash_command(description="Catalog, index, and API links")
        async def site(inter):
            await self.answer(inter, self.command_site)

    async def setup_hook(self):
        self.session = aiohttp.ClientSession(headers={"user-agent": "hzmods-bot", "accept": "application/json"})
        secret = os.environ.get("NOTIFY_SECRET", "").strip()
        if not secret:
            LOG.info("notify server is off until NOTIFY_SECRET is set")
            return
        app = web.Application()
        app.router.add_post("/notify", self.on_notify)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        await web.TCPSite(self._runner, NOTIFY_HOST, NOTIFY_PORT).start()
        LOG.info("notify listening on %s:%s", NOTIFY_HOST, NOTIFY_PORT)

    async def close(self):
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        if self.session is not None:
            await self.session.close()
            self.session = None
        await super().close()

    async def on_ready(self):
        if self._booted:
            return
        self._booted = True
        LOG.info("logged in as %s", self.user)
        await self.register_commands()
        self.loop.create_task(self.poll())

    async def register_commands(self):
        try:
            channel = self.get_channel(BAN_CHANNEL_ID) or await self.fetch_channel(BAN_CHANNEL_ID)
            guild = channel.guild
            await self.bulk_overwrite_guild_commands(guild.id, [command.body for command in self.slash_commands])
            LOG.info("slash commands registered")
        except (disnake.HTTPException, AttributeError):
            LOG.warning("slash command registration failed")

    async def on_member_join(self, member):
        role = member.guild.get_role(AUTO_ROLE_ID)
        if role is None:
            LOG.warning("auto role is not in this guild")
            return
        try:
            await member.add_roles(role, reason="auto role")
        except disnake.HTTPException:
            LOG.warning("auto role failed for %s", member.id)

    async def punish(self, guild, user_id):
        me = guild.me
        if me is not None and user_id == me.id:
            return
        try:
            await guild.ban(
                disnake.Object(id=user_id),
                clean_history_duration=0,
                reason="Wrote in the closed channel",
            )
        except disnake.HTTPException:
            LOG.warning("ban failed for %s", user_id)

    async def wipe(self, channel):
        async with self.purge_lock:
            try:
                await channel.purge(limit=None, bulk=True, reason="closed channel")
            except disnake.HTTPException:
                LOG.warning("purge failed")

    async def on_message(self, message):
        if message.channel.id != BAN_CHANNEL_ID or message.guild is None:
            return
        author = message.author
        if not author.bot and message.webhook_id is None:
            await self.punish(message.guild, author.id)
        await self.wipe(message.channel)

    async def block(self, inter):
        if inter.channel_id != BAN_CHANNEL_ID:
            return False
        if inter.guild is not None and not inter.user.bot:
            await self.punish(inter.guild, inter.user.id)
        if inter.channel is not None:
            await self.wipe(inter.channel)
        return True

    async def answer(self, inter, factory):
        if await self.block(inter):
            return
        try:
            await defer_v2(inter)
        except disnake.HTTPException:
            LOG.warning("interaction ack failed")
            return
        try:
            box = await factory()
        except Exception:
            LOG.warning("command failed")
            box = container([text_display("The site did not respond.")])
        try:
            await inter.edit_original_response(components=[box], allowed_mentions=MENTIONS)
        except disnake.HTTPException:
            LOG.warning("interaction edit failed")

    async def command_site(self):
        return reply_site()

    async def command_recent(self):
        feed = await get_json(self.session, "/api/v1/feed?limit=5")
        return reply_recent((feed or {}).get("versions") or [])

    async def command_user(self, name):
        username = str(name or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9_]{3,24}", username):
            return container([text_display("Name: 3–24 characters, letters, digits, and _.")])
        found = await get_json(self.session, "/api/v1/users/" + urllib.parse.quote(username))
        if not found:
            return container([text_display("No profile with that name.")])
        return reply_user(found)

    async def command_mod(self, query):
        query = str(query or "").strip().lower()
        found = None
        if re.fullmatch(r"[a-z0-9_]{1,64}", query):
            found = await get_json(self.session, "/api/v1/mods/" + urllib.parse.quote(query))
        if found:
            return reply_mod(found)
        listed = await get_json(self.session, "/api/v1/mods?q=" + urllib.parse.quote(query))
        projects = (listed or {}).get("projects") or []
        if len(projects) == 1:
            found = await get_json(self.session, "/api/v1/mods/" + urllib.parse.quote(projects[0]["id"]))
            if found:
                return reply_mod(found)
        return reply_mod(None, projects)

    async def push(self, box, files, message_id):
        if not WEBHOOK_URL or self.session is None:
            return None
        try:
            hook = disnake.Webhook.from_url(WEBHOOK_URL, session=self.session)
        except ValueError:
            LOG.warning("webhook url is invalid")
            return None
        try:
            if message_id:
                message = await hook.edit_message(
                    int(message_id),
                    components=[box],
                    attachments=[],
                    files=files or disnake.utils.MISSING,
                    allowed_mentions=MENTIONS,
                )
            else:
                kwargs = {"files": files} if files else {}
                message = await hook.send(
                    components=[box],
                    wait=True,
                    allowed_mentions=MENTIONS,
                    **kwargs,
                )
        except disnake.NotFound:
            return None
        except disnake.HTTPException as exc:
            LOG.warning("webhook status %s", exc.status)
            return None
        return str(message.id)

    async def deliver(self, item, message_id=None):
        files, skipped = await collect(self.session, item)
        page = same_origin(SITE_URL, item.get("page") or "/")
        box = announcement(item, files, page, skipped)
        mid = await self.push(box, upload_files(files, item), message_id)
        if message_id and not mid:
            mid = await self.push(box, upload_files(files, item), None)
        return mid

    async def announce_item(self, item, event):
        version_id = str(item.get("versionId") or "")
        if not version_id:
            return
        async with self.lock:
            messages = self.state.setdefault("messages", {})
            seen = set(self.state.setdefault("seen", []))
            if event == "media" and version_id in messages:
                mid = await self.deliver(item, messages[version_id])
                if mid:
                    messages[version_id] = mid
                    save_state(self.state)
                return
            if version_id in messages or version_id in seen:
                return
            mid = await self.deliver(item, None)
            if not mid:
                return
            messages[version_id] = mid
            save_state(self.state)
            LOG.info("announced %s", version_id)

    async def seed(self):
        if self.state.get("seeded"):
            return
        data = await get_json(self.session, "/api/v1/feed?limit=40")
        if data is None:
            LOG.warning("feed was not reachable, seed will retry")
            return
        seen = set(self.state.get("seen") or [])
        for item in data.get("versions") or []:
            version_id = str(item.get("versionId") or "")
            if version_id:
                seen.add(version_id)
        self.state["seen"] = sorted(seen)
        self.state["seeded"] = True
        save_state(self.state)
        LOG.info("seeded %s existing versions", len(seen))

    async def poll(self):
        await asyncio.sleep(2)
        while not self.is_closed():
            try:
                if not self.state.get("seeded"):
                    await self.seed()
                else:
                    data = await get_json(self.session, "/api/v1/feed?limit=40")
                    if data is not None:
                        for item in reversed(data.get("versions") or []):
                            await self.announce_item(item, "published")
            except Exception:
                LOG.warning("poll failed")
            await asyncio.sleep(POLL_SECONDS)

    async def on_notify(self, request):
        if not secret_ok(request.headers.get("Authorization", ""), os.environ.get("NOTIFY_SECRET", "").strip()):
            return web.Response(status=401, text="unauthorized")
        try:
            item = await request.json()
        except Exception:
            return web.Response(status=400, text="bad json")
        event = item.get("event") or "published"
        if event not in ("published", "media"):
            return web.Response(status=400, text="bad event")
        asyncio.create_task(self.announce_item(item, event))
        return web.Response(status=204)


def configure():
    global AUTO_ROLE_ID, BAN_CHANNEL_ID, SITE_URL, WEBHOOK_URL, NOTIFY_HOST, NOTIFY_PORT, POLL_SECONDS
    load_env(ROOT / ".env")
    AUTO_ROLE_ID = int(os.environ.get("AUTO_ROLE_ID", AUTO_ROLE_ID))
    BAN_CHANNEL_ID = int(os.environ.get("BAN_CHANNEL_ID", BAN_CHANNEL_ID))
    SITE_URL = os.environ.get("SITE_URL", SITE_URL).rstrip("/")
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip()
    NOTIFY_HOST = os.environ.get("NOTIFY_HOST", NOTIFY_HOST).strip() or "127.0.0.1"
    NOTIFY_PORT = int(os.environ.get("NOTIFY_PORT", NOTIFY_PORT))
    POLL_SECONDS = max(15, int(os.environ.get("POLL_SECONDS", POLL_SECONDS)))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    configure()
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token:
        raise SystemExit("Set DISCORD_TOKEN in bot/.env")
    if not WEBHOOK_URL:
        raise SystemExit("Set WEBHOOK_URL in bot/.env")
    HzBot().run(token)


if __name__ == "__main__":
    main()
