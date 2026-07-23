import httpx
import pytest
import respx

from src.transcript.api_provider import ApiTranscriptProvider
from src.transcript.base import TranscriptUnavailable

BASE = "https://api.supadata.ai/v1"


@respx.mock
def test_fetch_maps_response_to_transcript():
    respx.get(f"{BASE}/transcript").mock(
        return_value=httpx.Response(
            200,
            json={
                "lang": "en",
                "content": [
                    {"text": "Hello there", "offset": 0},
                    {"text": "second bit", "offset": 5500},
                ],
            },
        )
    )
    provider = ApiTranscriptProvider(api_key="k", base_url=BASE)
    result = provider.fetch("abc123")

    assert result is not None
    assert result.language == "en"
    assert result.segments[0].start_seconds == 0
    assert result.segments[1].start_seconds == 5
    assert result.full_text == "Hello there second bit"


@respx.mock
def test_fetch_sends_api_key_header():
    route = respx.get(f"{BASE}/transcript").mock(
        return_value=httpx.Response(200, json={"lang": "en", "content": []})
    )
    ApiTranscriptProvider(api_key="secret-key", base_url=BASE).fetch("abc123")
    assert route.calls.last.request.headers["x-api-key"] == "secret-key"


@respx.mock
def test_fetch_requests_native_mode_for_the_video_url():
    route = respx.get(f"{BASE}/transcript").mock(
        return_value=httpx.Response(200, json={"lang": "en", "content": []})
    )
    ApiTranscriptProvider(api_key="k", base_url=BASE).fetch("abc123")

    params = route.calls.last.request.url.params
    assert params["url"] == "https://www.youtube.com/watch?v=abc123"
    assert params["mode"] == "native"


@respx.mock
def test_fetch_returns_none_when_transcript_unavailable():
    respx.get(f"{BASE}/transcript").mock(return_value=httpx.Response(206))
    provider = ApiTranscriptProvider(api_key="k", base_url=BASE)
    assert provider.fetch("abc123") is None


@respx.mock
def test_fetch_returns_none_when_video_not_found():
    respx.get(f"{BASE}/transcript").mock(return_value=httpx.Response(404))
    provider = ApiTranscriptProvider(api_key="k", base_url=BASE)
    assert provider.fetch("abc123") is None


@respx.mock
def test_fetch_raises_on_async_job_response():
    respx.get(f"{BASE}/transcript").mock(return_value=httpx.Response(202, json={"jobId": "j1"}))
    provider = ApiTranscriptProvider(api_key="k", base_url=BASE)
    with pytest.raises(TranscriptUnavailable):
        provider.fetch("abc123")


@respx.mock
def test_fetch_raises_on_rate_limit():
    respx.get(f"{BASE}/transcript").mock(return_value=httpx.Response(429))
    provider = ApiTranscriptProvider(api_key="k", base_url=BASE)
    with pytest.raises(TranscriptUnavailable):
        provider.fetch("abc123")


@respx.mock
def test_fetch_raises_on_server_error():
    respx.get(f"{BASE}/transcript").mock(return_value=httpx.Response(503))
    provider = ApiTranscriptProvider(api_key="k", base_url=BASE)
    with pytest.raises(TranscriptUnavailable):
        provider.fetch("abc123")


@respx.mock
def test_fetch_raises_on_network_error():
    respx.get(f"{BASE}/transcript").mock(side_effect=httpx.ConnectError("boom"))
    provider = ApiTranscriptProvider(api_key="k", base_url=BASE)
    with pytest.raises(TranscriptUnavailable):
        provider.fetch("abc123")
