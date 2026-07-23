from src.shared.models import Section, Summary, Transcript, TranscriptSegment, VideoMeta


def test_transcript_full_text_joins_segments():
    t = Transcript(
        video_id="abc123",
        segments=[
            TranscriptSegment(start_seconds=0, text="Hello"),
            TranscriptSegment(start_seconds=5, text="world"),
        ],
        language="en",
    )
    assert t.full_text == "Hello world"


def test_transcript_roundtrips_through_dict():
    t = Transcript(
        video_id="abc123",
        segments=[TranscriptSegment(start_seconds=12, text="hi")],
        language="en",
    )
    assert Transcript.from_dict(t.to_dict()) == t


def test_summary_from_dict_builds_sections():
    s = Summary.from_dict(
        {
            "verdict": "Skip it.",
            "tldr": "Not much here.",
            "takeaways": ["one", "two"],
            "sections": [{"start_seconds": 0, "title": "Intro", "summary": "Framing."}],
            "tags": ["python"],
        }
    )
    assert s.sections[0] == Section(start_seconds=0, title="Intro", summary="Framing.")
    assert s.takeaways == ["one", "two"]


def test_video_meta_holds_fields():
    v = VideoMeta(
        video_id="abc123",
        title="A Title",
        channel="A Channel",
        published_at="2026-07-01T00:00:00Z",
        duration_seconds=3862,
    )
    assert v.duration_seconds == 3862
