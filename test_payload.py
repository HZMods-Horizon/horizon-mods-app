import json
import unittest

from payload import attachment_name, build_announcement, pack_files, same_origin


def walk(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


class PayloadTest(unittest.TestCase):
    def test_components_v2_has_no_embed_and_no_stripe(self):
        files = [
            {"name": "shot-1.png", "kind": "image", "caption": "frame"},
            {"name": "clip.mp4", "kind": "video", "caption": ""},
        ]
        payload = build_announcement(
            {"name": "Demo", "summary": "short", "version": "1.2.0", "channel": "release", "game": "26.3", "owner": "ada", "changelog": "first"},
            files,
            "https://hzmods.lol/mods/demo",
        )
        raw = json.dumps(payload)
        self.assertEqual(payload["flags"], 32768)
        self.assertNotIn("embeds", payload)
        self.assertNotIn("content", payload)
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertFalse(any(key == "accent_color" for key, _item in walk(payload)))
        self.assertIn("attachment://shot-1.png", raw)
        self.assertIn("attachment://clip.mp4", raw)
        names = [row["filename"] for row in payload["attachments"]]
        self.assertEqual(names, ["shot-1.png", "clip.mp4"])
        container = payload["components"][0]
        self.assertEqual(container["type"], 17)
        self.assertNotIn("accent_color", container)

    def test_pack_skips_what_does_not_fit_and_keeps_names(self):
        packed, skipped = pack_files([
            {"kind": "video", "ext": "mp4", "caption": "", "data": b"v" * 8_000_000},
            {"kind": "image", "ext": "png", "caption": "a", "data": b"p" * 2_000_000},
            {"kind": "image", "ext": "jpg", "caption": "b", "data": b"q" * 100},
        ])
        self.assertEqual(skipped, 1)
        self.assertEqual([item["name"] for item in packed], ["shot-1.png", "shot-2.jpg"])
        self.assertEqual(attachment_name("image", "webp", 2), "shot-2.webp")

    def test_same_origin_rejects_other_hosts(self):
        self.assertEqual(same_origin("https://hzmods.lol", "/mods/demo/media/1"), "https://hzmods.lol/mods/demo/media/1")
        self.assertEqual(same_origin("https://hzmods.lol", "https://evil.example/mods/1"), "")
        self.assertEqual(same_origin("https://hzmods.lol", "http://127.0.0.1/mods/1"), "")


class WebhookEditTest(unittest.TestCase):
    def test_edit_keeps_components_query(self):
        import bot
        from disnake.webhook.async_ import AsyncWebhookAdapter

        seen = {}

        def request(self, route, session, **kwargs):
            seen["method"] = route.method
            seen["params"] = kwargs.get("params")
            return "coro"

        adapter = AsyncWebhookAdapter()
        adapter.request = request.__get__(adapter, AsyncWebhookAdapter)
        result = adapter.edit_webhook_message(1, "token", 2, session=None, payload={})
        self.assertEqual(result, "coro")
        self.assertEqual(seen["method"], "PATCH")
        self.assertEqual(seen["params"]["with_components"], "true")

    def test_slash_commands_are_local(self):
        import bot

        hz = bot.HzBot()
        bodies = {command.name: command.body for command in hz.slash_commands}
        self.assertEqual(sorted(bodies), ["mod", "recent", "site", "user"])
        self.assertEqual(bodies["mod"].description, "Look up a mod on hzmods")
        self.assertEqual(bodies["mod"].options[0].description, "Mod id or part of the name")
        self.assertEqual(bodies["user"].options[0].description, "Name from hzmods")
        self.assertEqual(bodies["recent"].description, "Latest published versions")
        self.assertEqual(bodies["site"].description, "Catalog, index, and API links")
        self.assertEqual(hz._command_sync_flags.sync_global_commands, False)


if __name__ == "__main__":
    unittest.main()
