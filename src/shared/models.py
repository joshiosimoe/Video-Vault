from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class VideoMeta:
    video_id: str
    title: str
    channel: str
    published_at: str
    duration_seconds: int


@dataclass(frozen=True)
class TranscriptSegment:
    start_seconds: int
    text: str


@dataclass(frozen=True)
class Transcript:
    video_id: str
    segments: list[TranscriptSegment]
    language: str

    @property
    def full_text(self) -> str:
        return " ".join(seg.text.strip() for seg in self.segments if seg.text.strip())

    def to_dict(self) -> dict:
        return {
            "video_id": self.video_id,
            "language": self.language,
            "segments": [{"start_seconds": s.start_seconds, "text": s.text} for s in self.segments],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Transcript:
        return cls(
            video_id=data["video_id"],
            language=data["language"],
            segments=[
                TranscriptSegment(start_seconds=int(s["start_seconds"]), text=s["text"])
                for s in data["segments"]
            ],
        )


@dataclass(frozen=True)
class Section:
    start_seconds: int
    title: str
    summary: str


@dataclass(frozen=True)
class Summary:
    verdict: str
    tldr: str
    takeaways: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> Summary:
        return cls(
            verdict=data["verdict"],
            tldr=data["tldr"],
            takeaways=list(data["takeaways"]),
            sections=[
                Section(
                    start_seconds=int(s["start_seconds"]),
                    title=s["title"],
                    summary=s["summary"],
                )
                for s in data["sections"]
            ],
            tags=list(data["tags"]),
        )
