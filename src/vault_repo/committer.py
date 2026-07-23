from __future__ import annotations

import base64

import httpx

DEFAULT_BASE_URL = "https://api.github.com"
MAX_ATTEMPTS = 2


class CommitFailed(Exception):
    """The note could not be committed to the vault repository."""


class VaultCommitter:
    def __init__(
        self,
        token: str,
        owner: str,
        repo: str,
        branch: str = "main",
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self._token = token
        self._owner = owner
        self._repo = repo
        self._branch = branch
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _contents_url(self, path: str) -> str:
        return f"{self._base_url}/repos/{self._owner}/{self._repo}/contents/{path}"

    def _current_sha(self, url: str) -> str | None:
        response = httpx.get(
            url,
            params={"ref": self._branch},
            headers=self._headers,
            timeout=self._timeout,
        )
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise CommitFailed(f"failed reading {url}: HTTP {response.status_code}")
        return response.json().get("sha")

    def commit_note(self, path: str, content: str, message: str) -> None:
        url = self._contents_url(path)
        last_status: int | None = None

        for _ in range(MAX_ATTEMPTS):
            body = {
                "message": message,
                "content": base64.b64encode(content.encode()).decode(),
                "branch": self._branch,
            }
            sha = self._current_sha(url)
            if sha is not None:
                body["sha"] = sha

            response = httpx.put(url, json=body, headers=self._headers, timeout=self._timeout)
            if response.status_code < 300:
                return
            last_status = response.status_code
            if response.status_code != 409:
                break

        raise CommitFailed(f"failed committing {path}: HTTP {last_status}")
