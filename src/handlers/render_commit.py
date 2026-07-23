from __future__ import annotations

import os
from datetime import UTC, datetime

from src.notes.renderer import note_path, render_note, render_stub_note
from src.shared.artifacts import build_summary_artifact, write_summary_artifact
from src.shared.config import get_parameter
from src.shared.models import Summary, VideoMeta
from src.shared.state_store import StateStore, Status
from src.vault_repo.committer import VaultCommitter


def _build_committer() -> VaultCommitter:
    return VaultCommitter(
        token=get_parameter(os.environ["GITHUB_TOKEN_PARAM"]),
        owner=os.environ["VAULT_REPO_OWNER"],
        repo=os.environ["VAULT_REPO_NAME"],
        branch=os.environ.get("VAULT_REPO_BRANCH", "main"),
    )


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _load_meta(store: StateStore, video_id: str) -> VideoMeta:
    item = store.get(video_id)
    if item is None:
        raise KeyError(f"no state row for {video_id}")
    return VideoMeta(
        video_id=item["video_id"],
        title=item["title"],
        channel=item["channel"],
        published_at=item["published_at"],
        duration_seconds=int(item["duration_seconds"]),
    )


def _commit(store: StateStore, meta: VideoMeta, content: str, verb: str) -> dict:
    path = note_path(meta)
    _build_committer().commit_note(path, content, f"{verb}: {meta.title}")
    store.set_status(meta.video_id, Status.DONE, note_path=path)
    return {"video_id": meta.video_id, "note_path": path}


def handler(event: dict, context) -> dict:
    store = StateStore(os.environ["STATE_TABLE"])
    meta = _load_meta(store, event["video_id"])
    summary = Summary.from_dict(event["summary"])
    today = _today()
    path = note_path(meta)

    # S3 first: a GitHub outage should cost a retry, not the summary.
    write_summary_artifact(
        build_summary_artifact(meta, summary, path, today),
        bucket=os.environ["CONTENT_BUCKET"],
    )

    content = render_note(meta, summary, saved_at=today, summarized_at=today)
    return _commit(store, meta, content, "feat: add note")


def stub_handler(event: dict, context) -> dict:
    store = StateStore(os.environ["STATE_TABLE"])
    meta = _load_meta(store, event["video_id"])
    content = render_stub_note(
        meta, saved_at=_today(), reason="no captions available for this video"
    )
    return _commit(store, meta, content, "feat: add stub note")
