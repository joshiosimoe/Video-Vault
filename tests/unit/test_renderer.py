import yaml

from src.notes.renderer import (
    format_timestamp,
    note_path,
    render_note,
    render_stub_note,
    slugify,
)
from src.shared.models import Section, Summary, VideoMeta

META = VideoMeta(
    video_id="dQw4w9WgXcQ",
    title='How "Scheduling" Works: A Deep/Dive',
    channel="Some Channel",
    published_at="2026-07-01T12:00:00Z",
    duration_seconds=3862,
)

SUMMARY = Summary(
    verdict="Worth watching 18:40-31:00.",
    tldr="It explains scheduling.",
    takeaways=["First point", "Second point"],
    sections=[
        Section(start_seconds=0, title="Intro", summary="Framing."),
        Section(start_seconds=1120, title="Custom scheduler", summary="The good part."),
    ],
    tags=["kubernetes", "scheduling"],
)


def test_format_timestamp_under_an_hour():
    assert format_timestamp(252) == "4:12"


def test_format_timestamp_over_an_hour():
    assert format_timestamp(3862) == "1:04:22"


def test_format_timestamp_zero():
    assert format_timestamp(0) == "0:00"


def test_slugify_strips_filesystem_unsafe_characters():
    assert slugify('How "Scheduling" Works: A Deep/Dive') == "How Scheduling Works A DeepDive"


def test_slugify_truncates_and_strips_trailing_dots():
    assert len(slugify("x" * 200)) == 80


def test_note_path_uses_year_and_video_id():
    assert note_path(META).startswith("Video Vault/2026/")
    assert note_path(META).endswith("-dQw4w9WgXcQ.md")


def test_render_note_contains_frontmatter_and_clickable_timestamps():
    out = render_note(META, SUMMARY, saved_at="2026-07-22", summarized_at="2026-07-22")
    assert out.startswith("---\n")
    assert 'video_id: "dQw4w9WgXcQ"' in out
    assert "status: summarized" in out
    assert "> **Verdict:** Worth watching 18:40-31:00." in out
    assert "- First point" in out
    assert "[18:40](https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1120)" in out
    assert 'duration: "1:04:22"' in out


def test_render_note_quotes_titles_containing_colons():
    out = render_note(META, SUMMARY, saved_at="2026-07-22", summarized_at="2026-07-22")
    assert 'title: "How \\"Scheduling\\" Works: A Deep/Dive"' in out


def test_render_stub_note_marks_missing_transcript():
    out = render_stub_note(META, saved_at="2026-07-22", reason="no captions available")
    assert "status: no-transcript" in out
    assert "no captions available" in out
    assert "https://www.youtube.com/watch?v=dQw4w9WgXcQ" in out


def test_render_note_frontmatter_round_trips_through_yaml():
    meta = VideoMeta(
        video_id="rocket9XYZa",
        title="Rocket Launch \U0001f680 Highlights",
        channel="Space Channel",
        published_at="2026-07-01T12:00:00Z",
        duration_seconds=125,
    )
    summary = Summary(
        verdict="Worth watching.",
        tldr="Rockets go up.",
        takeaways=["Liftoff was clean"],
        sections=[Section(start_seconds=0, title="Launch", summary="Liftoff.")],
        tags=["space:launch", "rockets"],
    )

    out = render_note(meta, summary, saved_at="2026-07-22", summarized_at="2026-07-22")

    _, frontmatter_block, _ = out.split("---\n", 2)
    parsed = yaml.safe_load(frontmatter_block)

    assert parsed["title"] == meta.title
    assert isinstance(parsed["title"].encode("utf-8"), bytes)

    assert isinstance(parsed["tags"], list)
    assert all(isinstance(tag, str) for tag in parsed["tags"])
    assert "space:launch" in parsed["tags"]
