from __future__ import annotations

import json
import re

from src.shared.models import Summary, VideoMeta

WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
TIMESTAMP_URL = "https://www.youtube.com/watch?v={video_id}&t={seconds}"

_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")


def format_timestamp(seconds: int) -> str:
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def slugify(title: str, max_len: int = 80) -> str:
    cleaned = _UNSAFE_CHARS.sub("", title)
    cleaned = _WHITESPACE.sub(" ", cleaned).strip()
    return cleaned[:max_len].rstrip(" .")


def note_path(meta: VideoMeta) -> str:
    year = meta.published_at[:4]
    return f"Video Vault/{year}/{slugify(meta.title)}-{meta.video_id}.md"


def _yaml_str(value: str) -> str:
    """JSON string literals are valid YAML strings and handle all escaping.

    ensure_ascii=False is required: the default \\uXXXX escaping emits UTF-16
    surrogate pairs for characters above U+FFFF (e.g. emoji), which JSON
    readers recombine but YAML readers do not, corrupting the value.
    """
    return json.dumps(value, ensure_ascii=False)


def _frontmatter(meta: VideoMeta, saved_at: str, extra: dict[str, str]) -> list[str]:
    lines = [
        "---",
        f"title: {_yaml_str(meta.title)}",
        f"channel: {_yaml_str(meta.channel)}",
        f"url: {WATCH_URL.format(video_id=meta.video_id)}",
        f"video_id: {_yaml_str(meta.video_id)}",
        f"duration: {_yaml_str(format_timestamp(meta.duration_seconds))}",
        f"published: {meta.published_at[:10]}",
        f"saved: {saved_at}",
    ]
    for key, value in extra.items():
        lines.append(f"{key}: {value}")
    lines.append("---")
    return lines


def render_note(meta: VideoMeta, summary: Summary, saved_at: str, summarized_at: str) -> str:
    tags = ", ".join(_yaml_str(tag) for tag in ["video-vault", *summary.tags])
    lines = _frontmatter(
        meta,
        saved_at,
        {
            "summarized": summarized_at,
            "tags": f"[{tags}]",
            "status": "summarized",
        },
    )

    lines += [
        "",
        f"# {meta.title}",
        "",
        f"> **Verdict:** {summary.verdict}",
        "",
        "## TL;DR",
        "",
        summary.tldr,
        "",
        "## Key takeaways",
        "",
    ]
    lines += [f"- {item}" for item in summary.takeaways]
    lines += ["", "## Sections", ""]

    for section in summary.sections:
        stamp = format_timestamp(section.start_seconds)
        url = TIMESTAMP_URL.format(video_id=meta.video_id, seconds=section.start_seconds)
        lines.append(f"- [{stamp}]({url}) — {section.title}: {section.summary}")

    lines.append("")
    return "\n".join(lines)


def render_stub_note(meta: VideoMeta, saved_at: str, reason: str) -> str:
    tags = ", ".join(_yaml_str(tag) for tag in ["video-vault", "no-transcript"])
    lines = _frontmatter(
        meta,
        saved_at,
        {"tags": f"[{tags}]", "status": "no-transcript"},
    )
    lines += [
        "",
        f"# {meta.title}",
        "",
        f"> **No summary available:** {reason}. This one needs watching.",
        "",
        f"[Watch on YouTube]({WATCH_URL.format(video_id=meta.video_id)})",
        "",
    ]
    return "\n".join(lines)
