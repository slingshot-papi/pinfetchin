"""
Pinterest Media Extractor Module
Multi-strategy extraction for Videos (MP4) and Images (Original/HD JPG/PNG/WebP).
Supports video pins, standard image pins, and multi-image carousel pins.
"""

import re
import json
import time
import logging
import threading
from collections import Counter
from urllib.parse import urlparse, urljoin
import requests
from requests.adapters import HTTPAdapter
import yt_dlp

logger = logging.getLogger(__name__)

# Cache for extracted pin metadata (clean_url -> (expires_at, data))
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_SECONDS = 900  # 15 minutes

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.pinterest.com/",
}

# Persistent HTTP session with connection pooling for fast repeated requests
_SESSION = requests.Session()
_SESSION.headers.update(HEADERS)
_adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20)
_SESSION.mount("https://", _adapter)
_SESSION.mount("http://", _adapter)


def clean_pinterest_url(url: str) -> str:
    """Clean and resolve any short URLs (pin.it) to canonical Pinterest URL."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # If it's a short pin.it link, resolve redirect
    parsed = urlparse(url)
    if "pin.it" in parsed.netloc:
        try:
            resp = _SESSION.head(url, allow_redirects=True, timeout=5)
            url = resp.url
        except Exception as e:
            logger.warning(f"Failed to resolve pin.it redirect: {e}")
            try:
                with _SESSION.get(url, allow_redirects=True, timeout=5, stream=True) as resp:
                    url = resp.url
            except Exception:
                pass
    return url


def extract_pin_id(url: str) -> str | None:
    """Extract numeric pin ID from a Pinterest URL."""
    match = re.search(r'/pin/(?:[\w-]+--)?(\d+)', url)
    if match:
        return match.group(1)
    match2 = re.search(r'(\d{10,25})', url)
    if match2:
        return match2.group(1)
    return None


def extract_with_ytdlp(url: str) -> dict | None:
    """Extract pin video information using yt-dlp."""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'nocheckcertificate': True,
        'noplaylist': True,
        'hls_prefer_native': True,
        'user_agent': USER_AGENT,
        'socket_timeout': 8,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None

            title = info.get('title') or "Pinterest Video"
            description = info.get('description') or ""
            thumbnail = info.get('thumbnail') or ""
            duration = info.get('duration') or 0
            uploader = info.get('uploader') or info.get('uploader_id') or "Pinterest Creator"
            uploader_url = info.get('uploader_url') or ""
            webpage_url = info.get('webpage_url') or url

            formats = info.get('formats', [])
            video_formats = []
            seen_urls = set()

            for f in formats:
                f_url = f.get('url', '')
                if not f_url or f_url in seen_urls:
                    continue
                seen_urls.add(f_url)

                height = f.get('height') or 0
                width = f.get('width') or 0
                format_id = f.get('format_id') or ''
                filesize = f.get('filesize') or f.get('filesize_approx')

                is_hls = '.m3u8' in f_url or 'hls' in format_id.lower()

                # Determine standard resolution tier (accounting for vertical videos)
                dim = min(width, height) if (width and height) else (height or width)
                if dim >= 1080:
                    quality = "1080p Full HD"
                elif dim >= 720 or '720p' in f_url:
                    quality = "720p HD"
                elif dim >= 480:
                    quality = "480p SD"
                elif dim >= 360:
                    quality = "360p Medium"
                elif dim >= 240:
                    quality = "240p Mobile"
                elif dim > 0:
                    quality = f"{dim}p"
                else:
                    if '720p' in f_url:
                        quality = "720p HD"
                    elif 'exp' in f_url.lower():
                        quality = "Standard HD"
                    else:
                        quality = "Default Video"

                video_formats.append({
                    'format_id': format_id,
                    'quality': quality,
                    'height': height,
                    'width': width,
                    'resolution': f"{width}x{height}" if width and height else quality,
                    'ext': 'mp4',
                    'url': f_url,
                    'filesize': filesize,
                    'is_hls': is_hls,
                    'is_direct_mp4': not is_hls and ('.mp4' in f_url),
                })

            # Sort formats: direct MP4s first, highest resolution first
            video_formats.sort(
                key=lambda x: (1 if x['is_direct_mp4'] else 0, x['height'] or 0),
                reverse=True
            )

            best_direct = next((f for f in video_formats if f['is_direct_mp4']), None)
            best_stream_url = best_direct['url'] if best_direct else (video_formats[0]['url'] if video_formats else None)

            if not best_stream_url and not video_formats:
                return None

            return {
                'success': True,
                'id': info.get('id') or extract_pin_id(url),
                'title': title,
                'description': description,
                'thumbnail': thumbnail,
                'duration': round(duration, 1) if duration else None,
                'duration_str': format_duration(duration) if duration else None,
                'uploader': uploader,
                'uploader_url': uploader_url,
                'webpage_url': webpage_url,
                'preview_url': best_stream_url,
                'formats': video_formats,
                'type': 'video'
            }
    except Exception as e:
        logger.warning(f"yt-dlp extraction failed for {url}: {e}")
        return None


def extract_with_pinterest_api(url: str, pin_id: str) -> dict | None:
    """Fallback extraction using Pinterest's internal PinResource API."""
    try:
        api_url = "https://www.pinterest.com/resource/PinResource/get/"
        params = {
            "source_url": f"/pin/{pin_id}/",
            "data": json.dumps({
                "options": {
                    "field_set_key": "unauth_react_main_pin",
                    "id": pin_id
                },
                "context": {}
            })
        }
        resp = requests.get(api_url, params=params, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return None

        data = resp.json().get('resource_response', {}).get('data', {})
        if not data:
            return None

        title = data.get('title') or data.get('grid_title') or "Pinterest Media"
        description = data.get('description') or ""
        uploader = data.get('pinner', {}).get('full_name') or data.get('pinner', {}).get('username') or "Pinterest User"
        uploader_url = f"https://www.pinterest.com/{data.get('pinner', {}).get('username')}/" if data.get('pinner', {}).get('username') else ""

        # Extract images
        images = data.get('images', {})
        thumbnail = ""
        for key in ['orig', '736x', '474x']:
            if key in images and images[key].get('url'):
                thumbnail = images[key]['url']
                break

        # Videos dictionary
        videos = data.get('videos', {}).get('video_list', {})
        video_formats = []
        seen = set()

        if isinstance(videos, dict):
            for v_key, v_info in videos.items():
                v_url = v_info.get('url')
                if not v_url or v_url in seen:
                    continue
                seen.add(v_url)
                width = v_info.get('width', 0)
                height = v_info.get('height', 0)
                is_hls = '.m3u8' in v_url

                quality = "720p HD" if height >= 720 or '720p' in v_url else (f"{height}p" if height else "HD")
                video_formats.append({
                    'format_id': v_key,
                    'quality': quality,
                    'height': height,
                    'width': width,
                    'resolution': f"{width}x{height}" if width and height else quality,
                    'ext': 'mp4',
                    'url': v_url,
                    'filesize': None,
                    'is_hls': is_hls,
                    'is_direct_mp4': not is_hls and ('.mp4' in v_url or 'expMp4' in v_url or '720p' in v_url),
                })

        if not video_formats:
            return None

        video_formats.sort(key=lambda x: (1 if x['is_direct_mp4'] else 0, x['height'] or 0), reverse=True)
        best_direct = next((f for f in video_formats if f['is_direct_mp4']), None)
        best_stream_url = best_direct['url'] if best_direct else video_formats[0]['url']

        return {
            'success': True,
            'id': pin_id,
            'title': title,
            'description': description,
            'thumbnail': thumbnail,
            'duration': None,
            'duration_str': None,
            'uploader': uploader,
            'uploader_url': uploader_url,
            'webpage_url': url,
            'preview_url': best_stream_url,
            'formats': video_formats,
            'type': 'video'
        }
    except Exception as e:
        logger.warning(f"Pinterest API extraction failed for {pin_id}: {e}")
        return None


def _classify_video_url(v_url: str, format_id: str = "", width: int = 0, height: int = 0) -> dict:
    """Build a normalized format entry for a Pinterest video URL."""
    is_hls = '.m3u8' in v_url or 'hls' in format_id.lower()
    dim = min(width, height) if (width and height) else (height or width)
    if dim >= 1080 or '/1080p/' in v_url:
        quality = "1080p Full HD"
    elif dim >= 720 or '/720p/' in v_url or '720p' in v_url:
        quality = "720p HD"
    elif dim >= 480 or '/480p/' in v_url:
        quality = "480p SD"
    elif dim >= 360 or '/360p/' in v_url:
        quality = "360p Medium"
    elif dim >= 240 or '/240p/' in v_url:
        quality = "240p Mobile"
    elif dim > 0:
        quality = f"{dim}p"
    elif 'expMp4' in v_url or 'exp' in v_url.lower():
        quality = "Standard HD"
    elif is_hls:
        quality = "HD Stream (HLS)"
    else:
        quality = "Default Video"

    return {
        'format_id': format_id or ('hls' if is_hls else 'mp4'),
        'quality': quality,
        'height': height or (720 if '720p' in v_url else 0),
        'width': width,
        'resolution': f"{width}x{height}" if width and height else quality,
        'ext': 'mp4',
        'url': v_url,
        'filesize': None,
        'is_hls': is_hls,
        'is_direct_mp4': not is_hls and ('.mp4' in v_url),
    }


def _parse_m3u8_variants(master_url: str) -> list[dict]:
    """Fetch a master .m3u8 playlist and extract individual resolution variants."""
    variants = []
    try:
        resp = _SESSION.get(master_url, timeout=4)
        if resp.status_code != 200 or "#EXTM3U" not in resp.text:
            return variants

        lines = [line.strip() for line in resp.text.splitlines() if line.strip()]
        for i, line in enumerate(lines):
            if line.startswith("#EXT-X-STREAM-INF:") and i + 1 < len(lines):
                next_line = lines[i + 1]
                if next_line.startswith("#"):
                    continue
                res_match = re.search(r'RESOLUTION=(\d+)x(\d+)', line)
                width = int(res_match.group(1)) if res_match else 0
                height = int(res_match.group(2)) if res_match else 0
                variant_url = urljoin(master_url, next_line)
                variants.append(_classify_video_url(variant_url, format_id=f"hls_{width}x{height}", width=width, height=height))
    except Exception as e:
        logger.debug(f"Failed to parse m3u8 variants from {master_url}: {e}")
    return variants


def _extract_videos_from_html(html: str) -> list[dict]:
    """Extract video URLs embedded in Pinterest's pin HTML JSON, expanding HLS into 3 quality tiers."""
    raw_urls: list[str] = []

    # Primary: "videos":{"videoUrls":[...]} in Relay / PWS JSON
    vid_block = re.search(r'"videos"\s*:\s*\{\s*"videoUrls"\s*:\s*\[([^\]]+)\]', html)
    if vid_block:
        raw_urls.extend(re.findall(r'https://v\d*\.pinimg\.com/videos/[^"\'\s<>]+', vid_block.group(1)))

    # Secondary: "video_list":{...}
    if not raw_urls:
        vlist_block = re.search(r'"video_list"\s*:\s*\{(.*?)\}\s*\}', html)
        if vlist_block:
            raw_urls.extend(re.findall(r'https://v\d*\.pinimg\.com/videos/[^"\'\s<>]+', vlist_block.group(1)))

    # Fallback: direct video URLs for the main pin (only if a video hash appears)
    if not raw_urls:
        all_v = re.findall(r'https://v\d*\.pinimg\.com/videos/[^"\'\s<>]+\.(?:mp4|m3u8)', html)
        if all_v:
            hash_match = re.search(r'/([a-f0-9]{32})\.(?:mp4|m3u8)', all_v[0])
            if hash_match:
                h = hash_match.group(1)
                raw_urls = [u for u in all_v if h in u]
            else:
                raw_urls = all_v[:6]

    direct_mp4s: list[dict] = []
    hls_masters: list[str] = []
    seen = set()

    for u in raw_urls:
        u = u.replace('\\u002F', '/').replace('\\/', '/')
        if u in seen or u.endswith('.mpd'):
            continue
        seen.add(u)
        if '.mp4' in u:
            direct_mp4s.append(_classify_video_url(u))
        elif '.m3u8' in u:
            hls_masters.append(u)

    # Prefer standard /hls/ master playlist over /h265/ for broad device compatibility
    hls_masters.sort(key=lambda u: 0 if '/hls/' in u else 1)

    hls_variants: list[dict] = []
    if hls_masters:
        hls_variants = _parse_m3u8_variants(hls_masters[0])

    # Combine direct MP4s + HLS variants, highest resolution first, direct MP4s prioritized
    all_formats = direct_mp4s + hls_variants
    if not all_formats and hls_masters:
        all_formats = [_classify_video_url(hls_masters[0])]

    all_formats.sort(
        key=lambda x: (1 if x['is_direct_mp4'] else 0, min(x['width'] or 0, x['height'] or 0) or (x['height'] or 0)),
        reverse=True,
    )

    # Deduplicate by quality tier so the user gets 3 clean, distinct download qualities
    selected: list[dict] = []
    seen_qualities: set[str] = set()
    for fmt in all_formats:
        q = fmt['quality']
        if q in seen_qualities:
            continue
        seen_qualities.add(q)
        selected.append(fmt)
        if len(selected) >= 3:
            break

    return selected


def extract_from_html(url: str, pin_id: str | None = None) -> dict | None:
    """
    Fast single-request HTML parser for Pinterest Videos, Image Pins, and Carousels.
    Extracts video streams (MP4/HLS) first if present, otherwise extracts high-res images.
    """
    try:
        resp = _SESSION.get(url, timeout=8)
        if resp.status_code != 200:
            return None

        html = resp.text

        # 1. Parse Title & Description
        title_match = re.search(r'<title>([^<]+)</title>', html)
        raw_title = title_match.group(1).strip() if title_match else "Pinterest Media"
        title = re.sub(r'\s*\|\s*Pinterest$', '', raw_title, flags=re.IGNORECASE).strip()

        desc_match = re.search(r'<meta\s+(?:name|property)="description"\s+content="([^"]*)"', html, re.IGNORECASE)
        description = desc_match.group(1).strip() if desc_match else ""

        og_image_match = re.search(r'<meta\s+(?:name|property)="og:image"\s+content="([^"]+)"', html, re.IGNORECASE)
        og_image = og_image_match.group(1).strip() if og_image_match else ""

        # Check for creator
        creator_match = re.search(r'"pinner":\{"username":"([^"]+)","full_name":"([^"]+)"', html)
        uploader = "Pinterest Creator"
        uploader_url = ""
        if creator_match:
            uploader = creator_match.group(2) or creator_match.group(1)
            uploader_url = f"https://www.pinterest.com/{creator_match.group(1)}/"

        resolved_id = pin_id or extract_pin_id(url) or "pin"

        # 2. Check for Video Pin in the already-fetched HTML
        video_formats = _extract_videos_from_html(html)
        if video_formats:
            best_direct = next((f for f in video_formats if f['is_direct_mp4']), None)
            best_stream_url = best_direct['url'] if best_direct else video_formats[0]['url']
            return {
                'success': True,
                'id': resolved_id,
                'title': title,
                'description': description,
                'thumbnail': og_image,
                'duration': None,
                'duration_str': None,
                'uploader': uploader,
                'uploader_url': uploader_url,
                'webpage_url': url,
                'preview_url': best_stream_url,
                'formats': video_formats,
                'type': 'video',
            }

        # 3. Otherwise extract image hashes (Image Pins & Carousels)
        pattern = r'i\.pinimg\.com/(?:originals|\d+x|\d+x\d+)/([a-f0-9]{2}/[a-f0-9]{2}/[a-f0-9]{2}/[a-f0-9]+\.(?:jpg|png|webp|gif))'
        matches = re.findall(pattern, html, re.IGNORECASE)
        if not matches:
            return None

        counter = Counter(matches)
        # Sort by frequency: main pin images appear multiple times
        top_hashes = [h for h, count in counter.most_common() if count >= 2]
        if not top_hashes and matches:
            top_hashes = [matches[0]]

        # Limit to 12 images for carousel
        top_hashes = top_hashes[:12]

        images_list = []
        formats = []

        for idx, h in enumerate(top_hashes):
            ext = h.split('.')[-1].lower()
            orig_url = f"https://i.pinimg.com/originals/{h}"
            u1200 = f"https://i.pinimg.com/1200x/{h}"
            u736 = f"https://i.pinimg.com/736x/{h}"
            u474 = f"https://i.pinimg.com/474x/{h}"

            img_resolutions = [
                {'quality': 'Original Max-Res', 'resolution': 'Original', 'url': orig_url, 'ext': ext},
                {'quality': '2K Ultra HD', 'resolution': '1200px', 'url': u1200, 'ext': ext},
                {'quality': 'Full HD', 'resolution': '736px', 'url': u736, 'ext': ext},
                {'quality': 'Standard HD', 'resolution': '474px', 'url': u474, 'ext': ext},
            ]

            images_list.append({
                'index': idx + 1,
                'hash': h,
                'ext': ext,
                'original_url': orig_url,
                'resolutions': img_resolutions
            })

            # Populate formats for primary image
            if idx == 0:
                for res in img_resolutions:
                    formats.append({
                        'format_id': f"image_{res['resolution']}",
                        'quality': res['quality'],
                        'resolution': res['resolution'],
                        'ext': ext,
                        'url': res['url'],
                        'is_image': True,
                        'is_direct_mp4': False,
                        'is_hls': False
                    })

        best_image = images_list[0]['original_url'] if images_list else ""

        return {
            'success': True,
            'id': resolved_id,
            'title': title,
            'description': description,
            'thumbnail': best_image,
            'duration': None,
            'duration_str': None,
            'uploader': uploader,
            'uploader_url': uploader_url,
            'webpage_url': url,
            'preview_url': best_image,
            'type': 'image',
            'is_carousel': len(images_list) > 1,
            'images': images_list,
            'formats': formats
        }
    except Exception as e:
        logger.warning(f"HTML extraction error: {e}")
        return None


def extract_pinterest_media(url: str) -> dict:
    """
    Main extraction interface. Resolves URL and attempts multiple strategies.
    Supports both Videos and High-Resolution Images (including carousels).
    """
    clean_url = clean_pinterest_url(url)

    # Check TTL cache
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(clean_url)
        if cached and cached[0] > now:
            return cached[1]

    pin_id = extract_pin_id(clean_url)

    # Strategy 1: Fast single-request HTML parser (handles both Video Pins & Image/Carousel Pins)
    data = extract_from_html(clean_url, pin_id)

    # Strategy 2: yt-dlp fallback for edge-case video pins
    if not data or not data.get('formats'):
        data = extract_with_ytdlp(clean_url)

    # Strategy 3: Pinterest internal API fallback
    if (not data or not data.get('formats')) and pin_id:
        api_data = extract_with_pinterest_api(clean_url, pin_id)
        if api_data:
            data = api_data

    if not data or not data.get('formats'):
        return {
            'success': False,
            'error': (
                "Could not extract video or image from this Pinterest link. "
                "Please verify that the link is from a public pin."
            )
        }

    # Enhance format list: filter duplicates
    unique_formats = []
    seen_urls = set()
    for f in data['formats']:
        u = f['url']
        if u in seen_urls:
            continue
        seen_urls.add(u)
        unique_formats.append(f)
    data['formats'] = unique_formats

    # Cache result for 15 minutes
    with _CACHE_LOCK:
        _CACHE[clean_url] = (time.monotonic() + _CACHE_TTL_SECONDS, data)
        if len(_CACHE) > 500:
            _CACHE.pop(next(iter(_CACHE)))

    return data


def format_duration(seconds: float | int) -> str:
    """Format duration in seconds to MM:SS or HH:MM:SS."""
    if not seconds:
        return ""
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
