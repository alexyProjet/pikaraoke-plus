"""Tests for the workshop (atelier) routes."""

import json
from unittest.mock import MagicMock, patch

import pytest
import werkzeug
from flask import Flask

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from pikaraoke.routes.atelier import atelier_bp

ROUTE_PREFIX = "pikaraoke.routes.atelier"


@pytest.fixture
def app():
    test_app = Flask(__name__)
    test_app.secret_key = "test"
    test_app.register_blueprint(atelier_bp)
    return test_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def route_mocks():
    """Patch external dependencies used by the atelier routes."""
    with (
        patch(f"{ROUTE_PREFIX}.get_karaoke_instance") as mock_get_instance,
        patch(f"{ROUTE_PREFIX}.is_admin", return_value=True) as mock_is_admin,
    ):
        mock_k = MagicMock()
        mock_k.song_manager.songs = ["/songs/Alpha---aaaaaaaaaaa.mp4"]
        mock_k.song_manager.display_name_from_path = lambda p: "Alpha"
        mock_k.atelier_manager.send_song.return_value = (True, "job123")
        mock_k.atelier_manager.mark_url_for_conversion.return_value = True
        mock_get_instance.return_value = mock_k
        yield {"karaoke": mock_k, "is_admin": mock_is_admin}


def _post_json(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type="application/json")


class TestAdminGate:
    @pytest.mark.parametrize(
        "method,url",
        [
            ("post", "/atelier/links"),
            ("post", "/atelier/send"),
            ("get", "/atelier/jobs"),
            ("get", "/atelier/songs"),
        ],
    )
    def test_non_admin_is_rejected(self, client, route_mocks, method, url):
        route_mocks["is_admin"].return_value = False
        response = getattr(client, method)(url)
        assert response.status_code == 403


class TestAddLinks:
    def test_downloads_each_link_without_queueing(self, client, route_mocks):
        response = _post_json(
            client,
            "/atelier/links",
            {"links": ["https://youtu.be/aaaaaaaaaaa", "https://youtu.be/bbbbbbbbbbb"]},
        )
        assert response.status_code == 200
        assert response.get_json()["added"] == 2
        calls = route_mocks["karaoke"].download_manager.queue_download.call_args_list
        assert len(calls) == 2
        assert calls[0].args[1] is False
        assert calls[0].kwargs.get("user") == "Atelier"

    def test_convert_flag_marks_urls(self, client, route_mocks):
        _post_json(
            client,
            "/atelier/links",
            {"links": ["https://youtu.be/aaaaaaaaaaa"], "convert": True},
        )
        route_mocks["karaoke"].atelier_manager.mark_url_for_conversion.assert_called_once()

    def test_invalid_link_is_reported_and_skipped(self, client, route_mocks):
        route_mocks["karaoke"].atelier_manager.mark_url_for_conversion.return_value = False
        response = _post_json(
            client, "/atelier/links", {"links": ["https://example.com/x"], "convert": True}
        )
        data = response.get_json()
        assert data["added"] == 0
        assert data["invalid"] == ["https://example.com/x"]
        route_mocks["karaoke"].download_manager.queue_download.assert_not_called()

    def test_empty_body_is_rejected(self, client, route_mocks):
        response = _post_json(client, "/atelier/links", {"links": []})
        assert response.status_code == 400


class TestSendSong:
    def test_known_song_is_sent(self, client, route_mocks):
        response = _post_json(
            client, "/atelier/send", {"song_path": "/songs/Alpha---aaaaaaaaaaa.mp4"}
        )
        assert response.status_code == 200
        assert response.get_json()["job_id"] == "job123"
        route_mocks["karaoke"].atelier_manager.send_song.assert_called_once_with(
            "/songs/Alpha---aaaaaaaaaaa.mp4", title="Alpha"
        )

    def test_unknown_song_is_rejected(self, client, route_mocks):
        response = _post_json(client, "/atelier/send", {"song_path": "/songs/hack.mp4"})
        assert response.status_code == 404

    def test_workshop_not_configured(self, client, route_mocks):
        route_mocks["karaoke"].atelier_manager = None
        response = _post_json(
            client, "/atelier/send", {"song_path": "/songs/Alpha---aaaaaaaaaaa.mp4"}
        )
        assert response.status_code == 400


class TestJobsAndSearch:
    def test_jobs_returns_manager_list(self, client, route_mocks):
        route_mocks["karaoke"].atelier_manager.list_jobs.return_value = [{"id": "j1"}]
        response = client.get("/atelier/jobs")
        assert response.get_json() == {"jobs": [{"id": "j1"}]}

    def test_jobs_empty_when_not_configured(self, client, route_mocks):
        route_mocks["karaoke"].atelier_manager = None
        assert client.get("/atelier/jobs").get_json() == {"jobs": []}

    def test_song_search_matches_display_name(self, client, route_mocks):
        response = client.get("/atelier/songs?q=alp")
        songs = response.get_json()["songs"]
        assert songs == [{"path": "/songs/Alpha---aaaaaaaaaaa.mp4", "name": "Alpha"}]

    def test_song_search_empty_query(self, client, route_mocks):
        assert client.get("/atelier/songs").get_json() == {"songs": []}
