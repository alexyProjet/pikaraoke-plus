"""PC-side workshop watcher: GPU vocal separation for PiKaraoke.

Watches the shared workshop folder for jobs dropped by the Pi
(see pikaraoke/lib/atelier_manager.py for the folder layout), separates
vocals with demucs (CUDA), remuxes the instrumental audio onto the original
video with ffmpeg, and delivers the result to the shared karaoke library.

Run it with the python of a venv where demucs is installed
(see atelier/installer_pc.ps1). Stdlib only besides the demucs subprocess.
"""

import argparse
import json
import logging
import logging.handlers
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime

DEFAULT_ATELIER = r"\\192.168.1.157\data\karaoke-atelier"
DEFAULT_LIBRARY = r"\\192.168.1.157\data\karaoke-bibliotheque"
POLL_SECONDS = 5
JOB_RETENTION_DAYS = 30
SINGLETON_PORT = 48765  # bound on localhost so only one watcher runs

# "Title---dQw4w9WgXcQ.mp4" (PiKaraoke) or "Title [dQw4w9WgXcQ].mp4" (yt-dlp)
_ID_SUFFIX_RE = re.compile(r"^(?P<title>.+?)(?P<id>---[A-Za-z0-9_-]{11}| \[[A-Za-z0-9_-]{11}\])$")
_PERCENT_RE = re.compile(rb"(\d{1,3})%")

# Audio codec to pair with a copied video stream, per container.
_AUDIO_CODEC = {
    ".mp4": ["-c:a", "aac", "-b:a", "192k"],
    ".mkv": ["-c:a", "aac", "-b:a", "192k"],
    ".mov": ["-c:a", "aac", "-b:a", "192k"],
    ".webm": ["-c:a", "libopus", "-b:a", "160k"],
}


def instrumental_name(source_name: str) -> str:
    """Derive the output filename, keeping the YouTube ID marker intact."""
    stem, extension = os.path.splitext(source_name)
    match = _ID_SUFFIX_RE.match(stem)
    if match:
        return f"{match.group('title')} (Instrumental){match.group('id')}{extension}"
    return f"{stem} (Instrumental){extension}"


class Watcher:
    def __init__(self, atelier: str, library: str) -> None:
        self.inbox = os.path.join(atelier, "entree")
        self.status_dir = os.path.join(atelier, "etat")
        self.library = library
        self.work_dir = os.path.join(os.path.expanduser("~"), "karaoke-atelier", "tmp")

    def run_forever(self) -> None:
        logging.info("Watcher started: %s -> %s", self.inbox, self.library)
        while True:
            try:
                self.process_pending()
                self.prune_old_jobs()
            except OSError as e:
                # Share unreachable (Pi off, network down): retry quietly.
                logging.warning("Share unavailable: %s", e)
            time.sleep(POLL_SECONDS)

    def pending_jobs(self) -> list[dict]:
        jobs = []
        for entry in os.listdir(self.inbox):
            if not entry.endswith(".json"):
                continue
            job = self._read_json(os.path.join(self.inbox, entry))
            if not job or "id" not in job or "file" not in job:
                continue
            status = self._read_json(self._status_path(job["id"])) or {}
            if status.get("state") in ("done", "error"):
                continue
            jobs.append(job)
        jobs.sort(key=lambda j: j.get("created", ""))
        return jobs

    def process_pending(self) -> None:
        for job in self.pending_jobs():
            source = os.path.join(self.inbox, job["file"])
            if not os.path.isfile(source):
                self.write_status(job["id"], "error", 0, "Source file missing")
                continue
            logging.info("Job %s: %s", job["id"], job.get("title", job["file"]))
            try:
                output_name = self.convert(job, source)
            except Exception as e:  # noqa: BLE001 -- job failure must not kill the loop
                logging.exception("Job %s failed", job["id"])
                self.write_status(job["id"], "error", 0, str(e)[:300])
            else:
                self.write_status(job["id"], "done", 100, "", output=output_name)
                try:
                    os.remove(source)
                except OSError:
                    pass
                logging.info("Job %s done: %s", job["id"], output_name)

    def convert(self, job: dict, source: str) -> str:
        """Separate vocals and rebuild a playable file. Returns the output name."""
        job_id = job["id"]
        self.write_status(job_id, "converting", 0, "")
        os.makedirs(self.work_dir, exist_ok=True)
        work = tempfile.mkdtemp(dir=self.work_dir)
        try:
            # Work on a local copy: demucs seeks a lot, SMB reads are slow.
            local_source = os.path.join(work, job["file"])
            shutil.copy2(source, local_source)

            no_vocals = self.run_demucs(job_id, local_source, work)

            source_name = self._original_name(job, source)
            output_name = instrumental_name(source_name)
            local_output = os.path.join(work, "sortie" + os.path.splitext(output_name)[1])
            self.remux(local_source, no_vocals, local_output)

            # Copy under a temp name then rename: the Pi scanner must never
            # see a half-written file.
            partial = os.path.join(self.library, output_name + ".part")
            shutil.copy2(local_output, partial)
            os.replace(partial, os.path.join(self.library, output_name))
            return output_name
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def run_demucs(self, job_id: str, local_source: str, work: str) -> str:
        """Run demucs with progress reporting; return the no_vocals wav path."""
        command = [
            sys.executable,
            "-m",
            "demucs",
            "--two-stems",
            "vocals",
            "-n",
            "htdemucs",
            "-o",
            os.path.join(work, "demucs"),
            local_source,
        ]
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        last_write = 0.0
        buffer = b""
        while True:
            chunk = process.stderr.read(256)
            if not chunk:
                break
            buffer = buffer[-64:] + chunk
            match = None
            for match in _PERCENT_RE.finditer(buffer):
                pass
            if match and time.monotonic() - last_write > 2:
                percent = min(int(match.group(1)), 99)
                self.write_status(job_id, "converting", percent, "")
                last_write = time.monotonic()
        process.wait()
        if process.returncode != 0:
            raise RuntimeError(f"demucs exited with code {process.returncode}")

        track = os.path.splitext(os.path.basename(local_source))[0]
        no_vocals = os.path.join(work, "demucs", "htdemucs", track, "no_vocals.wav")
        if not os.path.isfile(no_vocals):
            raise RuntimeError("demucs produced no no_vocals.wav")
        return no_vocals

    def remux(self, source: str, no_vocals: str, output: str) -> None:
        """Attach the instrumental track to the original video (or audio only)."""
        extension = os.path.splitext(output)[1].lower()
        if extension in _AUDIO_CODEC and self._has_video_stream(source):
            command = [
                "ffmpeg", "-y", "-v", "error",
                "-i", source, "-i", no_vocals,
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "copy", *_AUDIO_CODEC[extension],
                output,
            ]  # fmt: skip
        else:
            command = ["ffmpeg", "-y", "-v", "error", "-i", no_vocals, output]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr[-300:]}")

    @staticmethod
    def _has_video_stream(path: str) -> bool:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=codec_name", "-of", "csv=p=0", path],
            capture_output=True,
            text=True,
        )  # fmt: skip
        return result.returncode == 0 and result.stdout.strip() != ""

    def _original_name(self, job: dict, source: str) -> str:
        """Rebuild the human filename: job title + original extension."""
        extension = os.path.splitext(source)[1]
        title = job.get("title") or os.path.splitext(job["file"])[0]
        safe_title = re.sub(r'[<>:"/\\|?*]', "_", title)
        return safe_title + extension

    def _status_path(self, job_id: str) -> str:
        return os.path.join(self.status_dir, job_id + ".json")

    def write_status(
        self, job_id: str, state: str, percent: int, message: str, output: str = ""
    ) -> None:
        os.makedirs(self.status_dir, exist_ok=True)
        path = self._status_path(job_id)
        data = {
            "id": job_id,
            "state": state,
            "percent": percent,
            "message": message,
            "output": output,
            "updated": datetime.now().isoformat(timespec="seconds"),
        }
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp_path, path)

    def prune_old_jobs(self) -> None:
        """Drop descriptor/status files of jobs finished long ago."""
        cutoff = time.time() - JOB_RETENTION_DAYS * 86400
        for folder in (self.inbox, self.status_dir):
            try:
                entries = os.listdir(folder)
            except OSError:
                continue
            for entry in entries:
                path = os.path.join(folder, entry)
                try:
                    if entry.endswith(".json") and os.path.getmtime(path) < cutoff:
                        os.remove(path)
                except OSError:
                    pass

    @staticmethod
    def _read_json(path: str) -> dict | None:
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None


def main() -> int:
    # The hf_xet download plugin aborts with "Fatal Error: HW capability" on
    # some machines; plain HTTP downloads work everywhere.
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--atelier", default=DEFAULT_ATELIER, help="shared workshop folder")
    parser.add_argument("--bibliotheque", default=DEFAULT_LIBRARY, help="shared library folder")
    args = parser.parse_args()

    log_path = os.path.join(os.path.expanduser("~"), "karaoke-atelier", "atelier.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        handlers=[
            logging.handlers.RotatingFileHandler(
                log_path, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
            )
        ],
    )

    # Single instance guard: the port stays bound for the process lifetime.
    guard = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        guard.bind(("127.0.0.1", SINGLETON_PORT))
    except OSError:
        logging.info("Another watcher is already running, exiting")
        return 0

    try:
        Watcher(args.atelier, args.bibliotheque).run_forever()
    except KeyboardInterrupt:
        logging.info("Stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
