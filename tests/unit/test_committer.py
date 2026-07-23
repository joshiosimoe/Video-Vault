import base64
import json

import httpx
import pytest
import respx

from src.vault_repo.committer import CommitFailed, VaultCommitter

BASE = "https://api.github.com"
CONTENTS = f"{BASE}/repos/me/vault/contents/Video Vault/2026/note.md"


def _committer() -> VaultCommitter:
    return VaultCommitter(token="t", owner="me", repo="vault", base_url=BASE)


@respx.mock
def test_creates_new_file_without_sha():
    respx.get(CONTENTS).mock(return_value=httpx.Response(404))
    put = respx.put(CONTENTS).mock(return_value=httpx.Response(201, json={}))

    _committer().commit_note("Video Vault/2026/note.md", "# hello", "feat: add note")

    body = json.loads(put.calls.last.request.content)
    assert "sha" not in body
    assert base64.b64decode(body["content"]).decode() == "# hello"
    assert body["branch"] == "main"


@respx.mock
def test_updates_existing_file_with_sha():
    respx.get(CONTENTS).mock(return_value=httpx.Response(200, json={"sha": "abc123"}))
    put = respx.put(CONTENTS).mock(return_value=httpx.Response(200, json={}))

    _committer().commit_note("Video Vault/2026/note.md", "# hello", "feat: update")

    assert json.loads(put.calls.last.request.content)["sha"] == "abc123"


@respx.mock
def test_sends_bearer_token():
    respx.get(CONTENTS).mock(return_value=httpx.Response(404))
    put = respx.put(CONTENTS).mock(return_value=httpx.Response(201, json={}))

    _committer().commit_note("Video Vault/2026/note.md", "x", "m")

    assert put.calls.last.request.headers["authorization"] == "Bearer t"


@respx.mock
def test_retries_once_on_sha_conflict():
    respx.get(CONTENTS).mock(
        side_effect=[
            httpx.Response(200, json={"sha": "stale"}),
            httpx.Response(200, json={"sha": "fresh"}),
        ]
    )
    put = respx.put(CONTENTS).mock(
        side_effect=[
            httpx.Response(409, json={"message": "conflict"}),
            httpx.Response(200, json={}),
        ]
    )

    _committer().commit_note("Video Vault/2026/note.md", "x", "m")

    assert put.call_count == 2
    assert json.loads(put.calls.last.request.content)["sha"] == "fresh"


@respx.mock
def test_raises_after_persistent_failure():
    respx.get(CONTENTS).mock(return_value=httpx.Response(404))
    respx.put(CONTENTS).mock(return_value=httpx.Response(500, json={}))

    with pytest.raises(CommitFailed):
        _committer().commit_note("Video Vault/2026/note.md", "x", "m")
