import httpx
import respx

from src.youtube.client import YouTubeClient, parse_iso_duration

API = "https://www.googleapis.com/youtube/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def _client() -> YouTubeClient:
    return YouTubeClient(
        client_id="cid",
        client_secret="secret",
        refresh_token="refresh",
        base_url=API,
        token_url=TOKEN_URL,
    )


def _mock_token():
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "at", "expires_in": 3600})
    )


def test_parse_iso_duration_full():
    assert parse_iso_duration("PT1H4M22S") == 3862


def test_parse_iso_duration_minutes_only():
    assert parse_iso_duration("PT4M12S") == 252


def test_parse_iso_duration_seconds_only():
    assert parse_iso_duration("PT45S") == 45


def test_parse_iso_duration_zero():
    assert parse_iso_duration("P0D") == 0


@respx.mock
def test_list_playlist_video_ids_paginates():
    _mock_token()
    respx.get(f"{API}/playlistItems").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "items": [{"contentDetails": {"videoId": "v1"}}],
                    "nextPageToken": "p2",
                },
            ),
            httpx.Response(200, json={"items": [{"contentDetails": {"videoId": "v2"}}]}),
        ]
    )
    assert _client().list_playlist_video_ids("PL123") == ["v1", "v2"]


@respx.mock
def test_get_video_metadata_maps_fields():
    _mock_token()
    respx.get(f"{API}/videos").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "v1",
                        "snippet": {
                            "title": "A Title",
                            "channelTitle": "A Channel",
                            "publishedAt": "2026-07-01T12:00:00Z",
                        },
                        "contentDetails": {"duration": "PT1H4M22S"},
                    }
                ]
            },
        )
    )
    [meta] = _client().get_video_metadata(["v1"])
    assert meta.video_id == "v1"
    assert meta.title == "A Title"
    assert meta.channel == "A Channel"
    assert meta.duration_seconds == 3862


@respx.mock
def test_get_video_metadata_batches_in_fifties():
    _mock_token()
    route = respx.get(f"{API}/videos").mock(return_value=httpx.Response(200, json={"items": []}))
    _client().get_video_metadata([f"v{i}" for i in range(120)])
    assert route.call_count == 3
