from __future__ import annotations

from src.shared.models import Transcript, VideoMeta

SYSTEM_PROMPT = """\
You summarize YouTube transcripts for a reader who does not have time to watch \
the video and wants to decide whether it is worth watching at all.

Rules:
- The verdict is the most important field. Say plainly whether the video is worth \
watching in full, worth skimming via this summary alone, or worth watching only a \
specific timestamp range. Be willing to say a video is not worth watching.
- Ground every takeaway in something actually said in the transcript. Do not \
generalize beyond it or add outside knowledge.
- start_seconds must be a real offset taken from the transcript timestamps, not an \
estimate. Sections must be in ascending chronological order.
- Aim for six to twelve sections on a one-hour video, scaled to length and density.
- Write plainly. No filler, no "in this video the speaker discusses" phrasing.\
"""


def build_user_message(meta: VideoMeta, transcript: Transcript) -> str:
    lines = [
        f"Title: {meta.title}",
        f"Channel: {meta.channel}",
        f"Duration: {meta.duration_seconds} seconds",
        "",
        "Transcript segments, formatted as [start_seconds] text:",
        "",
    ]
    lines += [f"[{seg.start_seconds}] {seg.text}" for seg in transcript.segments]
    return "\n".join(lines)
