"""Workshop page: prepare party downloads and follow PC conversions."""

import flask_babel
from flask import jsonify, redirect, render_template, request, url_for
from flask_smorest import Blueprint

from pikaraoke.lib.current_app import get_karaoke_instance, get_site_name, is_admin

_ = flask_babel.gettext

atelier_bp = Blueprint("atelier", __name__)

MAX_LINKS_PER_REQUEST = 50
MAX_SONG_RESULTS = 20


@atelier_bp.route("/atelier")
def atelier_page():
    """Workshop page (admin only)."""
    if not is_admin():
        return redirect(url_for("home.home"))
    k = get_karaoke_instance()
    return render_template(
        "atelier.html",
        site_title=get_site_name(),
        # MSG: Title of the workshop page (song preparation and conversions).
        title=_("Workshop"),
        atelier_enabled=k.atelier_manager is not None,
    )


@atelier_bp.route("/atelier/links", methods=["POST"])
def add_links():
    """Download a batch of YouTube links to the library, optionally marking
    them for instrumental conversion on the PC."""
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 403
    k = get_karaoke_instance()
    data = request.get_json(silent=True) or {}
    links = [link.strip() for link in data.get("links", []) if link.strip()]
    convert = bool(data.get("convert"))
    if not links:
        return jsonify({"error": "No links provided"}), 400
    links = links[:MAX_LINKS_PER_REQUEST]

    added = 0
    invalid = []
    for link in links:
        if convert and k.atelier_manager:
            if not k.atelier_manager.mark_url_for_conversion(link):
                invalid.append(link)
                continue
        k.download_manager.queue_download(link, False, user="Atelier")
        added += 1
    return jsonify({"added": added, "invalid": invalid})


@atelier_bp.route("/atelier/songs")
def search_songs():
    """Search the library by display name, for the send-to-workshop picker."""
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 403
    k = get_karaoke_instance()
    query = request.args.get("q", "").strip().lower()
    results = []
    if query:
        for song_path in k.song_manager.songs:
            name = k.song_manager.display_name_from_path(song_path)
            if query in name.lower():
                results.append({"path": song_path, "name": name})
                if len(results) >= MAX_SONG_RESULTS:
                    break
    return jsonify({"songs": results})


@atelier_bp.route("/atelier/send", methods=["POST"])
def send_song():
    """Send an existing library song to the PC workshop."""
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 403
    k = get_karaoke_instance()
    if not k.atelier_manager:
        return jsonify({"error": "Workshop not configured"}), 400
    data = request.get_json(silent=True) or {}
    song_path = data.get("song_path", "")
    if song_path not in k.song_manager.songs:
        return jsonify({"error": "Unknown song"}), 404
    ok, message = k.atelier_manager.send_song(
        song_path, title=k.song_manager.display_name_from_path(song_path)
    )
    if not ok:
        return jsonify({"error": message}), 500
    return jsonify({"job_id": message})


@atelier_bp.route("/atelier/jobs")
def jobs():
    """Current and recent workshop jobs, merged with PC-side statuses."""
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 403
    k = get_karaoke_instance()
    if not k.atelier_manager:
        return jsonify({"jobs": []})
    return jsonify({"jobs": k.atelier_manager.list_jobs()})
