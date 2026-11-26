"""
Flask Application for Pinterest Video Downloader
Compatible across desktop, tablet, and mobile devices (iOS, Android, etc.)
"""

import os
import re
import json
import time
import uuid
import mimetypes
import logging
import subprocess
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import unquote
import requests
from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    Response,
    send_from_directory,
    stream_with_context,
)

from extractor import extract_pinterest_media, clean_pinterest_url

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
TAKEDOWN_LOG_PATH = os.path.join(BASE_DIR, "takedown_requests.jsonl")

CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "contact@pinfetch.app")

app = Flask(__name__, static_folder=STATIC_DIR, template_folder=TEMPLATES_DIR)


# ---------------------------------------------------------------------------
# Thread-safe Sliding Window Rate Limiter
# ---------------------------------------------------------------------------
class SlidingWindowRateLimiter:
    """In-memory per-IP sliding window rate limiter to prevent server overload."""

    def __init__(self):
        self._buckets: dict[str, dict[str, deque]] = defaultdict(lambda: defaultdict(deque))
        self._lock = threading.Lock()

    def is_allowed(self, bucket: str, client_ip: str, max_requests: int, window_seconds: int) -> tuple[bool, int, int]:
        """
        Check if request is within rate limit.
        Returns (allowed, remaining, retry_after_seconds).
        """
        now = time.monotonic()
        cutoff = now - window_seconds

        with self._lock:
            timestamps = self._buckets[bucket][client_ip]
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            if len(timestamps) >= max_requests:
                retry_after = max(1, int(timestamps[0] + window_seconds - now) + 1)
                return False, 0, retry_after

            timestamps.append(now)
            remaining = max_requests - len(timestamps)
            return True, remaining, 0


rate_limiter = SlidingWindowRateLimiter()
_takedown_lock = threading.Lock()


def get_client_ip() -> str:
    """Resolve client IP address, accounting for reverse proxies."""
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if forwarded:
        return forwarded
    real_ip = request.headers.get("X-Real-IP", "").strip()
    if real_ip:
        return real_ip
    return request.remote_addr or "unknown"


def rate_limit(bucket: str, max_requests: int, window_seconds: int, json_response: bool = True):
    """Decorator enforcing per-IP sliding window rate limiting."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            client_ip = get_client_ip()
            allowed, remaining, retry_after = rate_limiter.is_allowed(
                bucket, client_ip, max_requests, window_seconds
            )
            if not allowed:
                logger.warning(f"Rate limit exceeded for {client_ip} on bucket '{bucket}'")
                msg = f"Too many requests. Please wait {retry_after} seconds before trying again."
                if json_response:
                    resp = jsonify({"success": False, "error": msg, "retry_after": retry_after})
                    resp.status_code = 429
                else:
                    resp = Response(msg, status=429, mimetype="text/plain")
                resp.headers["Retry-After"] = str(retry_after)
                resp.headers["X-RateLimit-Limit"] = str(max_requests)
                resp.headers["X-RateLimit-Remaining"] = "0"
                return resp

            result = fn(*args, **kwargs)
            if isinstance(result, Response):
                result.headers["X-RateLimit-Limit"] = str(max_requests)
                result.headers["X-RateLimit-Remaining"] = str(remaining)
            return result
        return wrapper
    return decorator


@app.context_processor
def inject_site_globals():
    """Make contact email and site metadata available to all templates."""
    return {
        "contact_email": CONTACT_EMAIL,
        "current_year": datetime.now().year,
    }

# Sample working pins for 1-click testing
SAMPLE_PINS = [
    {
        "title": "Origami Paper Craft Video",
        "url": "https://www.pinterest.com/pin/664281013778109217/",
        "label": "Origami Craft (1080p Video)"
    },
    {
        "title": "Cool Kitchen Gadgets",
        "url": "https://www.pinterest.com/pin/1084663891475263837/",
        "label": "Kitchen Gadgets (HD Video)"
    },
    {
        "title": "Norse Goddess Digital Art",
        "url": "https://www.pinterest.com/pin/7036943152646399/",
        "label": "Digital Art (Original HD Image)"
    }
]


def sanitize_filename(filename: str) -> str:
    """Make filename safe for Content-Disposition."""
    # Remove invalid characters
    cleaned = re.sub(r'[\\/*?:"<>|]', "", filename)
    cleaned = cleaned.replace(" ", "_")
    cleaned = cleaned.strip("._")
    if not cleaned:
        cleaned = "pinterest_video"
    return cleaned[:80]


@app.route("/")
def index():
    """Render the main mobile-friendly web application."""
    return render_template("index.html")


@app.route("/api/sample")
def get_sample():
    """Return sample pins for 1-click test."""
    return jsonify({"samples": SAMPLE_PINS})


@app.route("/api/extract", methods=["POST"])
@rate_limit("extract", max_requests=15, window_seconds=60, json_response=True)
def api_extract():
    """Extract metadata and formats for a Pinterest URL."""
    try:
        data = request.get_json(silent=True) or {}
        raw_url = data.get("url", "").strip()

        if not raw_url:
            return jsonify({"success": False, "error": "Please enter a valid Pinterest URL."}), 400

        # Validate Pinterest URL pattern
        if not re.search(r'(pinterest\.[a-z.]+|pin\.it|pinimg\.com)', raw_url, re.IGNORECASE):
            return jsonify({
                "success": False,
                "error": "Please enter a valid Pinterest URL (e.g. https://pinterest.com/pin/... or https://pin.it/...)."
            }), 400

        result = extract_pinterest_media(raw_url)
        if not result.get("success"):
            return jsonify(result), 400

        return jsonify(result)
    except Exception as e:
        logger.error(f"Error in api_extract: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": f"An error occurred while fetching video details: {str(e)}"
        }), 500


@app.route("/api/download")
@rate_limit("download", max_requests=30, window_seconds=60, json_response=False)
def api_download():
    """
    Stream video/image file from Pinterest to client as a downloadable file.
    Guarantees videos are downloaded in .mp4 format.
    Supports HTTP Range requests and on-the-fly HLS remuxing.
    """
    target_url = request.args.get("url", "").strip()
    custom_title = request.args.get("title", "pinterest_video").strip()
    media_type = request.args.get("type", "video").strip()

    if not target_url:
        return "Missing url parameter", 400

    # Ensure target is from trusted pinterest CDN
    parsed = re.match(r'^https?://([^/]+)', target_url)
    if not parsed or not re.search(r'(pinimg\.com|pinterest\.com)', parsed.group(1)):
        return "Invalid download URL origin", 403

    safe_title = sanitize_filename(custom_title)
    is_image = (media_type == "image") or any(target_url.lower().endswith(x) for x in ['.jpg', '.jpeg', '.png', '.webp', '.gif'])
    if is_image:
        if ".png" in target_url.lower():
            img_ext = "png"
            content_type = "image/png"
        elif ".webp" in target_url.lower():
            img_ext = "webp"
            content_type = "image/webp"
        else:
            img_ext = "jpg"
            content_type = "image/jpeg"
        filename = f"{safe_title}.{img_ext}"
    else:
        filename = f"{safe_title}.mp4"
        content_type = "video/mp4"

    # Case 1: Video stream is an HLS .m3u8 playlist -> remux to MP4 on-the-fly using ffmpeg
    if not is_image and ".m3u8" in target_url:
        try:
            cmd = [
                "ffmpeg", "-y",
                "-i", target_url,
                "-c", "copy",
                "-bsf:a", "aac_adtstoasc",
                "-movflags", "frag_keyframe+empty_moov+default_base_moof",
                "-f", "mp4",
                "pipe:1"
            ]
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=10**6
            )

            def generate_hls_mp4():
                try:
                    while True:
                        data = proc.stdout.read(64 * 1024)
                        if not data:
                            break
                        yield data
                finally:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except Exception:
                        pass

            return Response(
                stream_with_context(generate_hls_mp4()),
                mimetype="video/mp4",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                    "Content-Type": "video/mp4",
                    "Cache-Control": "public, max-age=3600",
                }
            )
        except Exception as e:
            logger.error(f"HLS to MP4 remux error: {e}")
            return f"Error converting video to MP4: {str(e)}", 500

    # Case 2: Direct file stream (MP4 video or JPG image)
    req_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.pinterest.com/",
    }

    # Pass client Range header if provided
    client_range = request.headers.get("Range")
    if client_range:
        req_headers["Range"] = client_range

    try:
        remote_resp = requests.get(target_url, headers=req_headers, stream=True, timeout=20)

        # Build response headers
        resp_headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600",
            "Content-Type": content_type
        }

        # Content-Length and Range
        if "Content-Length" in remote_resp.headers:
            resp_headers["Content-Length"] = remote_resp.headers["Content-Length"]
        if "Content-Range" in remote_resp.headers:
            resp_headers["Content-Range"] = remote_resp.headers["Content-Range"]

        status_code = remote_resp.status_code if remote_resp.status_code in [200, 206] else 200

        def generate():
            for chunk in remote_resp.iter_content(chunk_size=64 * 1024):
                if chunk:
                    yield chunk

        return Response(
            stream_with_context(generate()),
            status=status_code,
            headers=resp_headers
        )
    except Exception as e:
        logger.error(f"Download stream error: {e}")
        return f"Error downloading file: {str(e)}", 500


@app.route("/api/audio")
@rate_limit("audio", max_requests=10, window_seconds=60, json_response=False)
def api_audio():
    """
    Extract audio track from video stream on-the-fly using ffmpeg as an MP3.
    """
    video_url = request.args.get("url", "").strip()
    title = request.args.get("title", "pinterest_audio").strip()

    if not video_url:
        return "Missing video url", 400

    safe_title = sanitize_filename(title)
    filename = f"{safe_title}.mp3"

    try:
        # ffmpeg command to extract MP3 to stdout pipe
        cmd = [
            "ffmpeg",
            "-y",
            "-i", video_url,
            "-vn",
            "-acodec", "libmp3lame",
            "-q:a", "2",
            "-f", "mp3",
            "pipe:1"
        ]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=10**6
        )

        def generate_audio():
            try:
                while True:
                    data = proc.stdout.read(64 * 1024)
                    if not data:
                        break
                    yield data
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except Exception:
                    pass

        return Response(
            stream_with_context(generate_audio()),
            mimetype="audio/mpeg",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-cache",
            }
        )
    except Exception as e:
        logger.error(f"Audio extraction error: {e}")
        return f"Error extracting audio: {str(e)}", 500


@app.route("/manifest.json")
def manifest():
    """PWA Web App Manifest."""
    return send_from_directory(STATIC_DIR, "manifest.json", mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
    """PWA Service Worker file."""
    response = send_from_directory(STATIC_DIR, "sw.js", mimetype="application/javascript")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.route("/api/health")
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "app": "PinFetch", "version": "2.0.0"})


@app.route("/privacy")
def privacy():
    """Privacy Policy page."""
    return render_template("privacy.html")


@app.route("/terms")
def terms():
    """Terms of Use page."""
    return render_template("terms.html")


@app.route("/takedown", methods=["GET", "POST"])
def takedown():
    """Takedown request page."""
    if request.method == "POST":
        form = request.form
        entry = {
            "id": str(uuid.uuid4()),
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "name": form.get("name", "").strip()[:100],
            "email": form.get("email", "").strip()[:200],
            "pin_url": form.get("pin_url", "").strip()[:500],
            "reason": form.get("reason", "").strip()[:2000],
            "ip": get_client_ip(),
        }
        with _takedown_lock:
            with open(TAKEDOWN_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        logger.info(f"Takedown request submitted: id={entry['id']} pin_url={entry['pin_url']}")
        return render_template("takedown.html", submitted=True)
    return render_template("takedown.html", submitted=False)


if __name__ == "__main__":
    import socket
    port = int(os.environ.get("PORT", 5000))

    # Discover host IP addresses
    wifi_ips = []
    vpn_ips = []
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if ip.startswith("192.168.") and not ip.startswith("192.168.56."):
                wifi_ips.append(ip)
            elif ip.startswith("10."):
                vpn_ips.append(ip)
    except Exception:
        pass

    print(f"\n=======================================================")
    print(f" PinFetch - Pinterest Video & Image Downloader")
    print(f"=======================================================")
    print(f" [PC / Laptop]:          http://localhost:{port}")
    if wifi_ips:
        for ip in wifi_ips:
            print(f" [Phone / Tablet Wi-Fi]: http://{ip}:{port}")
    if vpn_ips:
        print(f"\n ⚠️ VPN Detected ({', '.join(vpn_ips)}):")
        print(f" If your phone cannot connect, enable 'Allow LAN' in your")
        print(f" VPN app, or temporarily pause the VPN so local devices connect.")
    print(f"=======================================================\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
