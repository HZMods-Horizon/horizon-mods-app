"""Discord Components V2 bodies built with disnake. No classic embed and no accent stripe."""

import disnake
from disnake.ui import ActionRow, Button, Container, File, MediaGallery, Separator, TextDisplay

FLAG = 32768


def text_display(content):
    body = str(content or "").strip() or "—"
    return TextDisplay(body[:4000])


def separator():
    return Separator()


def link_row(pairs):
    buttons = []
    for label, url in pairs[:5]:
        if not url:
            continue
        buttons.append(Button(
            style=disnake.ButtonStyle.link,
            label=str(label)[:80] or "Open",
            url=url,
        ))
    if not buttons:
        return None
    return ActionRow(*buttons)


def link_button(label, url):
    return link_row([(label, url)])


def media_gallery(items):
    gallery = []
    for item in items[:10]:
        description = str(item.get("description") or "")[:1024]
        gallery.append(disnake.MediaGalleryItem(
            media=item["url"],
            description=description or None,
        ))
    return MediaGallery(*gallery)


def file_display(url):
    return File(url)


def container(children):
    # accent_colour is left unset on purpose: that field is the colored side stripe.
    return Container(*(child for child in children if child is not None))


def v2_message(children):
    return {
        "flags": FLAG,
        "allowed_mentions": {"parse": []},
        "components": [container(children).to_component_dict()],
    }
