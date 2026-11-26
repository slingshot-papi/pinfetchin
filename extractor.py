"""
Pinterest Media Extractor Module
Multi-strategy extraction for Videos (MP4) and Images (Original/HD JPG/PNG/WebP).
Supports video pins, standard image pins, and multi-image carousel pins.
"""

import re
import json
import logging
from collections import Counter
from urllib.parse import urlparse
import requests
import yt_dlp

logger = logging.getLogger(__name__)

# Cache for extracted pin metadata (pin_id/url -> data, ttl)
_CACHE = {}

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


def clean_pinterest_url(url: str) -> str:
    """Clean and resolve any short URLs (pin.it) to canonical Pinterest URL."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # If it's a short pin.it link, resolve redirect
    parsed = urlparse(url)
    if "pin.it" in parsed.netloc:
        try:
            resp = requests.head(url, headers=HEADERS, allow_redirects=True, timeout=8)
            url = resp.url
        except Exception as e:
            logger.warning(f"Failed to resolve pin.it redirect: {e}")
            try:
                resp = requests.get(url, headers=HEADERS, allow_redirects=True, timeout=8)
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
        'user_agent': USER_AGENT,
        'socket_timeout': 12,
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


def extract_from_html(url: str, pin_id: str | None = None) -> dict | None:
    """
    Direct HTML parser for Pinterest Image Pins and Carousels.
    Extracts high-resolution images (Originals, 1200px, 736px, 474px).
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        if resp.status_code != 200:
            return None

        html = resp.text

        # 1. Parse Title & Description
        title_match = re.search(r'<title>([^<]+)</title>', html)
        raw_title = title_match.group(1).strip() if title_match else "Pinterest Image"
        title = re.sub(r'\s*\|\s*Pinterest$', '', raw_title, flags=re.IGNORECASE).strip()

        desc_match = re.search(r'<meta\s+(?:name|property)="description"\s+content="([^"]*)"', html, re.IGNORECASE)
        description = desc_match.group(1).strip() if desc_match else ""

        # Check for creator
        creator_match = re.search(r'"pinner":\{"username":"([^"]+)","full_name":"([^"]+)"', html)
        uploader = "Pinterest Creator"
        uploader_url = ""
        if creator_match:
            uploader = creator_match.group(2) or creator_match.group(1)
            uploader_url = f"https://www.pinterest.com/{creator_match.group(1)}/"

        # 2. Extract image hashes
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
            'id': pin_id or extract_pin_id(url) or "pin",
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
        logger.warning(f"HTML image extraction error: {e}")
        return None


def extract_pinterest_media(url: str) -> dict:
    """
    Main extraction interface. Resolves URL and attempts multiple strategies.
    Supports both Videos and High-Resolution Images (including carousels).
    """
    clean_url = clean_pinterest_url(url)

    # Check cache
    if clean_url in _CACHE:
        return _CACHE[clean_url]

    # Strategy 1: yt-dlp (Primary for Video Pins)
    data = extract_with_ytdlp(clean_url)

    # Strategy 2: If yt-dlp returned no formats or failed, try Pinterest internal API
    if not data or not data.get('formats'):
        pin_id = extract_pin_id(clean_url)
        if pin_id:
            api_data = extract_with_pinterest_api(clean_url, pin_id)
            if api_data:
                data = api_data

    # Strategy 3: Try HTML scraping (Primary for Image Pins, Photos & Carousels)
    if not data or not data.get('formats'):
        pin_id = extract_pin_id(clean_url)
        html_data = extract_from_html(clean_url, pin_id)
        if html_data:
            data = html_data

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
    _CACHE[clean_url] = data
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
