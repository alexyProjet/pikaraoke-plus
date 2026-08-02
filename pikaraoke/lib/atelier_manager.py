"""Bridge to the PC conversion workshop (GPU vocal separation).

The Pi and the PC exchange work through a shared folder (a Samba share both
machines can reach). The Pi drops job requests in ``<atelier>/entree`` (a copy
of the source file plus a JSON descriptor); the PC watcher
(``atelier/atelier_pc.py``) writes progress to ``<atelier>/etat`` and delivers
the converted file to the karaoke library. Everything is plain files so either
side can restart without losing state.
"""

import json
import logging
import os
import re
import shutil
import uuid
from datetime import datetime

import gevent

from pikaraoke.lib.youtube_dl import get_youtube_id_from_url

# Matches the two supported filename patterns: "Title---dQw4w9WgXcQ.mp4"
# (PiKaraoke) and "Title [dQw4w9WgXcQ].mp4" (yt-dlp).
_VIDEO_ID_RE = re.compile(r"(?:---|\[)([A-Za-z0-9_-]{11})\]?\.[^.]+$")

# Terminal states written by the PC watcher.
_FINISHED_STATES = {"done", "error"}

_MAX_PENDING_CONVERSIONS = 100
_MAX_LISTED_JOBS = 30


def video_id_from_path(song_path: str) -> str | None:
    """Extract the 11-character YouTube ID from a song filename, if present."""
    match = _VIDEO_ID_RE.search(os.path.basename(song_path))
    return match.group(1) if match else None


class AtelierManager:
    """Manage conversion jobs exchanged with the PC workshop."""

    def __init__(self, atelier_path: str, events=None, sync_library=None) -> None:
        """Initialize the manager.

        Args:
            atelier_path: Shared folder both the Pi and the PC can reach.
            events: EventSystem used to surface notifications.
            sync_library: Callable that refreshes the song library, invoked
                once per job when its converted file lands in the library.
        """
        self.atelier_path = atelier_path
        self.inbox_dir = os.path.join(atelier_path, "entree")
        self.status_dir = os.path.join(atelier_path, "etat")
        self._events = events
        self._sync_library = sync_library
        self._synced_jobs: set[str] = set()
        self._pending_conversions: set[str] = set()

    def _run_async(self, fn, *args) -> None:
        """Run fn in the hub threadpool so file copies never block the server."""
        gevent.get_hub().threadpool.spawn(fn, *args)

    def mark_url_for_conversion(self, video_url: str) -> bool:
        """Remember that a URL being downloaded should go to the workshop.

        Returns False when no YouTube ID could be extracted from the URL.
        """
        video_id = get_youtube_id_from_url(video_url)
        if not video_id:
            return False
        if len(self._pending_conversions) >= _MAX_PENDING_CONVERSIONS:
            logging.warning("Atelier: pending conversion list full, ignoring %s", video_url)
            return False
        self._pending_conversions.add(video_id)
        return True

    def on_song_downloaded(self, song_path: str) -> None:
        """Send a freshly downloaded song to the workshop if it was marked."""
        video_id = video_id_from_path(song_path)
        if video_id is None or video_id not in self._pending_conversions:
            return
        self._pending_conversions.discard(video_id)
        self.send_song(song_path)

    def send_song(self, song_path: str, title: str | None = None) -> tuple[bool, str]:
        """Queue a library song for conversion by the PC.

        Copies the file into the shared inbox in the background, then writes
        the job descriptor (the descriptor is written last so the PC never
        picks up a half-copied file).
        """
        if not os.path.isfile(song_path):
            return (False, f"File not found: {song_path}")
        job_id = uuid.uuid4().hex[:12]
        self._run_async(self._send_song_sync, job_id, song_path, title)
        return (True, job_id)

    def _send_song_sync(self, job_id: str, song_path: str, title: str | None) -> None:
        extension = os.path.splitext(song_path)[1]
        job = {
            "id": job_id,
            "title": title or os.path.splitext(os.path.basename(song_path))[0],
            "file": job_id + extension,
            "created": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            os.makedirs(self.inbox_dir, exist_ok=True)
            os.makedirs(self.status_dir, exist_ok=True)
            shutil.copy2(song_path, os.path.join(self.inbox_dir, job["file"]))
            self._write_json(os.path.join(self.inbox_dir, job_id + ".json"), job)
            logging.info("Atelier: job %s created for %s", job_id, song_path)
        except OSError as e:
            logging.error("Atelier: failed to create job for %s: %s", song_path, e)
            if self._events:
                self._events.emit(
                    "notification", f"Could not send song to the workshop: {e}", "danger"
                )

    @staticmethod
    def _write_json(path: str, data: dict) -> None:
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp_path, path)

    @staticmethod
    def _read_json(path: str) -> dict | None:
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def list_jobs(self) -> list[dict]:
        """Merge job descriptors with the statuses written by the PC.

        Newest jobs first, capped at a screenful. When a job just finished,
        trigger one library sync so the converted file shows up.
        """
        jobs = []
        try:
            entries = [e for e in os.listdir(self.inbox_dir) if e.endswith(".json")]
        except OSError:
            return jobs
        for entry in entries:
            job = self._read_json(os.path.join(self.inbox_dir, entry))
            if not job or "id" not in job:
                continue
            status = self._read_json(os.path.join(self.status_dir, job["id"] + ".json")) or {}
            job["state"] = status.get("state", "waiting")
            job["percent"] = status.get("percent", 0)
            job["message"] = status.get("message", "")
            job["output"] = status.get("output", "")
            jobs.append(job)
        jobs.sort(key=lambda j: j.get("created", ""), reverse=True)
        self._sync_new_completions(jobs)
        return jobs[:_MAX_LISTED_JOBS]

    def _sync_new_completions(self, jobs: list[dict]) -> None:
        needs_sync = False
        for job in jobs:
            if job["state"] == "done" and job["id"] not in self._synced_jobs:
                self._synced_jobs.add(job["id"])
                needs_sync = True
        if needs_sync and self._sync_library:
            self._sync_library()
