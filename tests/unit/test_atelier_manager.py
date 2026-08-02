"""Tests for AtelierManager (PC workshop bridge)."""

import json
import os
from unittest.mock import MagicMock

import pytest

from pikaraoke.lib.atelier_manager import AtelierManager, video_id_from_path


@pytest.fixture
def atelier(tmp_path):
    """AtelierManager on a temp folder, with async copies made synchronous."""
    manager = AtelierManager(str(tmp_path), sync_library=MagicMock())
    manager._run_async = lambda fn, *args: fn(*args)
    return manager


def _write_song(tmp_path, name="Some Song---dQw4w9WgXcQ.mp4"):
    song = tmp_path / name
    song.write_bytes(b"fake video data")
    return str(song)


class TestVideoIdFromPath:
    def test_pikaraoke_pattern(self):
        assert video_id_from_path("/songs/Title---dQw4w9WgXcQ.mp4") == "dQw4w9WgXcQ"

    def test_ytdlp_pattern(self):
        assert video_id_from_path("/songs/Title [dQw4w9WgXcQ].webm") == "dQw4w9WgXcQ"

    def test_no_id(self):
        assert video_id_from_path("/songs/Recording.mp4") is None


class TestSendSong:
    def test_creates_media_copy_and_descriptor(self, atelier, tmp_path):
        song = _write_song(tmp_path)
        ok, job_id = atelier.send_song(song, title="Some Song")
        assert ok

        media = os.path.join(atelier.inbox_dir, job_id + ".mp4")
        descriptor = os.path.join(atelier.inbox_dir, job_id + ".json")
        assert os.path.isfile(media)
        with open(descriptor, encoding="utf-8") as f:
            job = json.load(f)
        assert job["id"] == job_id
        assert job["title"] == "Some Song"
        assert job["file"] == job_id + ".mp4"

    def test_title_defaults_to_filename(self, atelier, tmp_path):
        song = _write_song(tmp_path)
        _, job_id = atelier.send_song(song)
        with open(os.path.join(atelier.inbox_dir, job_id + ".json"), encoding="utf-8") as f:
            assert json.load(f)["title"] == "Some Song---dQw4w9WgXcQ"

    def test_missing_file_fails(self, atelier):
        ok, message = atelier.send_song("/nowhere/nothing.mp4")
        assert not ok
        assert "not found" in message.lower()


class TestConversionMarking:
    def test_marked_download_is_sent(self, atelier, tmp_path):
        song = _write_song(tmp_path)
        assert atelier.mark_url_for_conversion("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        atelier.on_song_downloaded(song)
        jsons = [f for f in os.listdir(atelier.inbox_dir) if f.endswith(".json")]
        assert len(jsons) == 1

    def test_unmarked_download_is_ignored(self, atelier, tmp_path):
        song = _write_song(tmp_path)
        atelier.on_song_downloaded(song)
        assert not os.path.isdir(atelier.inbox_dir)

    def test_mark_is_consumed_once(self, atelier, tmp_path):
        song = _write_song(tmp_path)
        atelier.mark_url_for_conversion("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        atelier.on_song_downloaded(song)
        atelier.on_song_downloaded(song)
        jsons = [f for f in os.listdir(atelier.inbox_dir) if f.endswith(".json")]
        assert len(jsons) == 1

    def test_invalid_url_rejected(self, atelier):
        assert not atelier.mark_url_for_conversion("https://example.com/not-youtube")


class TestListJobs:
    def _make_job(self, atelier, job_id, created, state=None, percent=0):
        os.makedirs(atelier.inbox_dir, exist_ok=True)
        os.makedirs(atelier.status_dir, exist_ok=True)
        with open(os.path.join(atelier.inbox_dir, job_id + ".json"), "w", encoding="utf-8") as f:
            json.dump(
                {"id": job_id, "title": job_id, "file": job_id + ".mp4", "created": created}, f
            )
        if state:
            with open(
                os.path.join(atelier.status_dir, job_id + ".json"), "w", encoding="utf-8"
            ) as f:
                json.dump({"id": job_id, "state": state, "percent": percent}, f)

    def test_empty_when_no_folder(self, atelier):
        assert atelier.list_jobs() == []

    def test_merges_status_and_sorts_newest_first(self, atelier):
        self._make_job(atelier, "aaa", "2026-08-01T10:00:00", state="converting", percent=40)
        self._make_job(atelier, "bbb", "2026-08-02T10:00:00")
        jobs = atelier.list_jobs()
        assert [job["id"] for job in jobs] == ["bbb", "aaa"]
        assert jobs[0]["state"] == "waiting"
        assert jobs[1]["state"] == "converting"
        assert jobs[1]["percent"] == 40

    def test_done_job_triggers_one_library_sync(self, atelier):
        self._make_job(atelier, "ccc", "2026-08-02T10:00:00", state="done", percent=100)
        atelier.list_jobs()
        atelier.list_jobs()
        assert atelier._sync_library.call_count == 1
