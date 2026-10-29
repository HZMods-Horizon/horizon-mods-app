"""Build a Components V2 announcement and keep attachment names inside the site origin."""

import urllib.parse

from components import FLAG, container, file_display, link_button, media_gallery, separator, text_display

TOTAL_BYTES = 9_500_000
EXTS = {"png", "jpg", "gif", "webp", "mp4", "webm"}
MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "mp4": "video/mp4",
    "webm": "video/webm",
}


def clip(value, limit):
    text = " ".join(str(value or "").split())
    return text[:limit]


def attachment_name(kind, ext, index):
    safe = ext if ext in EXTS else "bin"
    if kind == "video":
        return f"clip.{safe}"
    return f"shot-{index}.{safe}"


def same_origin(base, path):
    root = str(base or "").rstrip("/")
    raw = str(path or "")
    if raw.startswith("http://") or raw.startswith("https://"):
        url = raw
    elif raw.startswith("/"):
        url = root + raw
    else:
        return ""
    got = urllib.parse.urlsplit(url)
    want = urllib.parse.urlsplit(root)
    if got.scheme not in ("http", "https") or not want.netloc or got.netloc != want.netloc:
        return ""
    return urllib.parse.urlunsplit((got.scheme, got.netloc, got.path, got.query, ""))


def pack_files(downloaded):
    """Keep images first, then the clip, until the webhook size budget is full."""
    ordered = sorted(downloaded, key=lambda item: 0 if item.get("kind") == "image" else 1)
    packed = []
    used = 0
    skipped = 0
    image_index = 0
    for item in ordered:
        data = item.get("data") or b""
        if not data or used + len(data) > TOTAL_BYTES:
            skipped += 1
            continue
        kind = "video" if item.get("kind") == "video" else "image"
        ext = item.get("ext") or "bin"
        if kind == "image":
            image_index += 1
            name = attachment_name("image", ext, image_index)
        else:
            name = attachment_name("video", ext, 1)
        used += len(data)
        packed.append({
            "name": name,
            "kind": kind,
            "caption": item.get("caption") or "",
            "data": data,
            "mime": MIME.get(ext, "application/octet-stream"),
        })
    return packed, skipped


def announcement(item, files, page_url, skipped=0):
    lines = [
        f"## {clip(item.get('name'), 200)}",
        clip(item.get("summary"), 300),
        f"**{clip(item.get('version'), 64)}** · {clip(item.get('channel'), 16)} · {clip(item.get('game'), 32)}",
        clip(item.get("owner"), 40),
    ]
    change = clip(item.get("changelog"), 700)
    if change:
        lines.append(change)
    if skipped:
        lines.append("Some files did not fit in this message. They stay on the mod page.")
    children = [text_display("\n".join(line for line in lines if line))]
    images = [row for row in files if row.get("kind") == "image"]
    videos = [row for row in files if row.get("kind") == "video"]
    if images:
        children.append(separator())
        children.append(media_gallery([
            {"url": f"attachment://{row['name']}", "description": row.get("caption") or item.get("name") or ""}
            for row in images
        ]))
    for video in videos:
        children.append(file_display(f"attachment://{video['name']}"))
    if page_url:
        children.append(link_button("Open mod", page_url))
    return container(children)


def build_announcement(item, files, page_url, skipped=0):
    payload = {
        "flags": FLAG,
        "allowed_mentions": {"parse": []},
        "components": [announcement(item, files, page_url, skipped).to_component_dict()],
    }
    if files:
        payload["attachments"] = [
            {"id": index, "filename": row["name"], "description": clip(row.get("caption") or item.get("name"), 256)}
            for index, row in enumerate(files)
        ]
    return payload
