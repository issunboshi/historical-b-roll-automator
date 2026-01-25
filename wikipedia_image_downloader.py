#!/usr/bin/env python3
"""
wikipedia_image_downloader.py

Search one or more terms on Wikipedia, find each page's first N images (default 10),
download them at original resolution, and organize them into subfolders
based on license level inside a folder named after the search term.

Usage:
  python3 wikipedia_image_downloader.py "Barack Obama"
  python3 wikipedia_image_downloader.py "Golden Gate Bridge" --limit 10 --output /path/to/save
  python3 wikipedia_image_downloader.py "Barack Obama" "Golden Gate Bridge" "New York City"
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote, urlparse, parse_qs

import csv
import random
import random
import requests
from bs4 import BeautifulSoup
import configparser
import datetime


WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
DEFAULT_USER_AGENT = "b-roll-finder/0.1 (Wikipedia image downloader; contact: local script)"

# Rate limiting and retry settings (can be overridden via CLI)
REQUEST_DELAY_S: float = 0.1
MAX_RETRIES: int = 5
RETRY_BACKOFF_S: float = 1.0
SVG_TO_PNG: bool = True
SVG_PNG_WIDTH: int = 3000
_SVG_IMPORT_FAILED_WARNED: bool = False

# Basename blacklist patterns to skip (case-insensitive, substring match)
BLACKLIST_BASENAME_PATTERNS = [
    "wikisource-logo",
    "commons-logo",
    "disambig_gray",
    "wiktionary-logo-en-v2",
]


def build_http_session(user_agent: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})
    return session


def search_wikipedia_page(session: requests.Session, query: str) -> Optional[Dict]:
    """
    Returns the top search result as a dict with 'pageid' and 'title' or None if no result.
    """
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": 1,
        "format": "json",
        "formatversion": 2,
        "utf8": 1,
        "maxlag": 5,
    }
    resp = http_get(session, WIKIPEDIA_API, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("query", {}).get("search", [])
    if not results:
        return None
    top = results[0]
    return {"pageid": top.get("pageid"), "title": top.get("title")}


def get_page_images(session: requests.Session, pageid: int) -> List[str]:
    """
    Returns a list of File: titles in order of appearance using parse/images.
    Note: This may include UI icons and non-content images.
    """
    params = {
        "action": "parse",
        "pageid": pageid,
        "prop": "images",
        "format": "json",
        "formatversion": 2,
        "utf8": 1,
        "maxlag": 5,
    }
    resp = http_get(session, WIKIPEDIA_API, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    images = data.get("parse", {}).get("images", []) or []
    # 'images' are bare file names without "File:" prefix sometimes; normalize to "File:" titles
    normalized = []
    for name in images:
        if not name:
            continue
        if not name.lower().startswith("file:"):
            normalized.append(f"File:{name}")
        else:
            normalized.append(name)
    # Keep unique order
    seen = set()
    ordered_unique = []
    for t in normalized:
        if t not in seen:
            seen.add(t)
            ordered_unique.append(t)
    return ordered_unique


def get_content_images(session: requests.Session, pageid: int) -> List[str]:
    """
    Parse the article HTML and extract file titles of images used in the main content
    ('.mw-parser-output') by looking for anchor tags linking to '/wiki/File:...'.
    This avoids UI/status icons like protection locks that live outside the content area.
    """
    params = {
        "action": "parse",
        "pageid": pageid,
        "prop": "text",
        "format": "json",
        "formatversion": 2,
        "utf8": 1,
        "maxlag": 5,
    }
    resp = http_get(session, WIKIPEDIA_API, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    html: str = data.get("parse", {}).get("text", "") or ""
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one(".mw-parser-output")
    if not content:
        content = soup  # fallback to whole document if structure changes
    file_titles: List[str] = []
    seen = set()

    # Look for anchors that link to File pages
    for a in content.select("a[href]"):
        href = a.get("href", "")
        title: Optional[str] = None
        if href.startswith("/wiki/File:"):
            # /wiki/File:Example.jpg
            title = unquote(href[len("/wiki/"):]).replace("_", " ")
        elif href.startswith("./File:"):
            # ./File:Example.jpg
            title = unquote(href[len("./"):]).replace("_", " ")
        elif href.startswith("/w/index.php"):
            # /w/index.php?title=File:Example.jpg&...
            parsed = urlparse(href)
            qs = parse_qs(parsed.query)
            tvals = qs.get("title") or []
            if tvals:
                title = unquote(tvals[0]).replace("_", " ")
        elif "/wiki/Special:FilePath/" in href:
            # /wiki/Special:FilePath/Example.jpg → derive File: title
            try:
                name = href.split("/wiki/Special:FilePath/", 1)[1]
                name = name.split("?", 1)[0]
                name = unquote(name).replace("_", " ")
                title = f"File:{name}"
            except Exception:
                title = None

        if not title:
            continue
        if not title.lower().startswith("file:"):
            title = f"File:{title}"
        # Skip obvious non-image by extension early
        if is_probably_non_image_title(title):
            continue
        if title not in seen:
            seen.add(title)
            file_titles.append(title)

    return file_titles


def filter_out_ui_icons(file_titles: List[str]) -> List[str]:
    """
    Filter out common UI/status icons and maintenance graphics that are not article content.
    This is heuristic-based and may be expanded over time.
    """
    if not file_titles:
        return file_titles
    blacklist_patterns = [
        r"padlock", r"lock", r"semi[- ]?protection", r"fully[- ]?protected", r"pp-",
        r"question[_-]?book", r"disambig", r"edit[- ]?clear", r"magnify", r"search",
        r"wikidata[- ]?logo", r"wikipedia[- ]?logo", r"commons[- ]?logo", r"oojs[_-]ui",
        r"nuvola", r"crystal[_- ]clear", r"gnome[-_]", r"external[- ]?link", r"ambox",
    ]
    blacklist_regex = re.compile("|".join(blacklist_patterns), re.IGNORECASE)
    filtered: List[str] = []
    for t in file_titles:
        # Only test the basename to avoid false positives in long titles
        basename = t.split(":", 1)[-1]
        if blacklist_regex.search(basename):
            continue
        filtered.append(t)
    return filtered


def is_probably_non_image_title(file_title: str) -> bool:
    """
    Heuristic filter based on file extension to skip audio/video files.
    """
    basename = file_title.split(":", 1)[-1].lower()
    non_image_exts = {
        "ogg", "oga", "ogv", "ogx", "opus", "spx",
        "webm", "mp4", "m4v", "mov", "avi", "mpg", "mpeg",
        "mp3", "wav", "flac", "midi", "mid", "aiff", "aac",
        "mka", "mkv",
    }
    # Extract extension if present
    if "." in basename:
        ext = basename.rsplit(".", 1)[-1]
        return ext in non_image_exts
    return False


def match_blacklist_pattern(file_title: str) -> Optional[str]:
    """
    Return the blacklist pattern that matches this title's basename, if any.
    """
    basename = file_title.split(":", 1)[-1].lower()
    for pattern in BLACKLIST_BASENAME_PATTERNS:
        if pattern in basename:
            return pattern
    return None


def is_image_mime(mime: Optional[str]) -> bool:
    if not mime:
        return False
    return mime.startswith("image/")

def is_symbolic_svg(file_title: str, mime: Optional[str], extmetadata: Dict) -> bool:
    """
    Detect obvious symbolic SVGs to skip (national/organizational symbols), including flags,
    coats of arms, and signatures/autographs.
    Conditions (heuristic):
      - MIME is image/svg+xml, AND
      - Title/object name/description mentions:
        'flag' OR 'coat of arms' OR 'signature'/'autograph' (common variants)
    """
    if mime != "image/svg+xml":
        return False
    def has_symbolic_phrase(s: str) -> bool:
        s = s.lower()
        if "flag" in s:
            return True
        # Common coat-of-arms variants
        if "coat of arms" in s or "coat_of_arms" in s or "coat-of-arms" in s:
            return True
        # Signature variants
        if "signature" in s or "autograph" in s:
            return True
        return False

    basename = file_title.split(":", 1)[-1].lower()
    if has_symbolic_phrase(basename):
        return True
    object_name = strip_html(get_meta_value(extmetadata, "ObjectName"))
    if has_symbolic_phrase(object_name):
        return True
    image_desc = strip_html(get_meta_value(extmetadata, "ImageDescription"))
    if has_symbolic_phrase(image_desc):
        return True
    return False


def _extract_year_candidates(text: str) -> List[int]:
    if not text:
        return []
    years: List[int] = []
    for m in re.findall(r"(?<!\d)(1\d{3}|20\d{2}|21\d{2})(?!\d)", text):
        try:
            y = int(m)
            if 1000 <= y <= 2100:
                years.append(y)
        except Exception:
            continue
    return years


def infer_image_year(title_key: str, extmetadata: Dict) -> Optional[int]:
    """
    Infer a plausible creation/publication year from metadata/title.
    Returns the smallest year found (older bias) or None.
    """
    fields = [
        get_meta_value(extmetadata, "DateTimeOriginal"),
        get_meta_value(extmetadata, "DateTime"),
        get_meta_value(extmetadata, "DateTimeDigitized"),
        get_meta_value(extmetadata, "Date"),
        get_meta_value(extmetadata, "ObjectName"),
        get_meta_value(extmetadata, "ImageDescription"),
        title_key.split(":", 1)[-1],
    ]
    candidates: List[int] = []
    for val in fields:
        if not val:
            continue
        plain = strip_html(val)
        candidates.extend(_extract_year_candidates(plain))
    if not candidates:
        return None
    return min(candidates)


def reorder_by_historical_priority(all_titles: List[str], metadata_map: Dict[str, Dict]) -> List[str]:
    """
    Reorder to prefer older images first (<= current_year - 30).
    Within historical group, older years first; then newer; unknown last.
    """
    current_year = datetime.datetime.now().year
    cutoff = current_year - 30
    scored: List[Tuple[int, int, int, str]] = []
    LARGE = 999999
    for i, t in enumerate(all_titles):
        meta = metadata_map.get(t) or {}
        extmeta = meta.get("extmetadata", {}) or {}
        y = infer_image_year(t, extmeta)
        if y is not None and y <= cutoff:
            scored.append((0, y, i, t))
        elif y is not None:
            scored.append((1, y, i, t))
        else:
            scored.append((2, LARGE, i, t))
    scored.sort(key=lambda x: (x[0], x[1], x[2]))
    return [t for (_, _, _, t) in scored]

def reorder_by_recent_priority(all_titles: List[str], metadata_map: Dict[str, Dict]) -> List[str]:
    """
    Reorder to prefer newer images first when a plausible year can be inferred.
    Unknown-year images go last; within groups, preserve stable ordering by index.
    """
    scored: List[Tuple[int, int, int, str]] = []
    LARGE_NEG = -999999
    for i, t in enumerate(all_titles):
        meta = metadata_map.get(t) or {}
        extmeta = meta.get("extmetadata", {}) or {}
        y = infer_image_year(t, extmeta)
        if y is not None:
            # Group 0: known year, sort by year descending (newer first)
            scored.append((0, -y, i, t))
        else:
            # Group 1: unknown, keep after known years
            scored.append((1, LARGE_NEG, i, t))
    scored.sort(key=lambda x: (x[0], x[1], x[2]))
    return [t for (_, _, _, t) in scored]

def strip_html(text: str) -> str:
    if not text:
        return ""
    try:
        return BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    except Exception:
        return text


def build_attribution_text(
    file_title: str,
    source_url: str,
    extmetadata: Dict,
    category_key: str,
) -> str:
    """
    Create a human-readable attribution string to save alongside the image.
    """
    object_name = strip_html(get_meta_value(extmetadata, "ObjectName")) or file_title.split(":", 1)[-1]
    artist = strip_html(get_meta_value(extmetadata, "Artist")) or strip_html(get_meta_value(extmetadata, "Author")) or strip_html(get_meta_value(extmetadata, "Credit"))
    license_short = get_meta_value(extmetadata, "LicenseShortName") or get_meta_value(extmetadata, "License")
    license_url = get_meta_value(extmetadata, "LicenseUrl")
    usage_terms = strip_html(get_meta_value(extmetadata, "UsageTerms"))
    attribution_required = (get_meta_value(extmetadata, "AttributionRequired") or "").lower() == "true"

    lines: List[str] = []
    lines.append(f"Title: {object_name}")
    if artist:
        lines.append(f"Author/Creator: {artist}")
    lines.append(f"Source file: {source_url}")
    if license_short:
        if license_url:
            lines.append(f"License: {license_short} ({license_url})")
        else:
            lines.append(f"License: {license_short}")
    if usage_terms:
        lines.append(f"Usage terms: {usage_terms}")

    if category_key in {"cc_by", "cc_by_sa", "other_cc"}:
        # Suggested plain-text attribution line
        # e.g., "“FileName” by Author is licensed under CC BY-SA 4.0 (link) via Wikimedia Commons."
        if artist and license_short:
            if license_url:
                lines.append(f"Suggested attribution: “{object_name}” by {artist} is licensed under {license_short} ({license_url}) via Wikimedia Commons.")
            else:
                lines.append(f"Suggested attribution: “{object_name}” by {artist} is licensed under {license_short} via Wikimedia Commons.")
        elif license_short:
            if license_url:
                lines.append(f"Suggested attribution: “{object_name}” is licensed under {license_short} ({license_url}) via Wikimedia Commons.")
            else:
                lines.append(f"Suggested attribution: “{object_name}” is licensed under {license_short} via Wikimedia Commons.")
        if attribution_required:
            lines.append("Note: Attribution is required.")
    elif category_key in {"restricted_nonfree"}:
        lines.append("Notice: This file is marked non-free/restricted. Review fair-use or local policy before reuse.")
    elif category_key in {"unknown"}:
        lines.append("Notice: License information is incomplete or unknown. Review the file page before reuse.")

    lines.append("Downloaded via Wikipedia Image Downloader (no changes made by downloader).")
    return "\n".join(lines) + "\n"


def write_attribution_sidecar(dest_path: Path, content: str) -> None:
    """
    Writes a sidecar text file next to the image, named like 'image.jpg.txt'.
    """
    sidecar_path = dest_path.with_name(dest_path.name + ".txt")
    with open(sidecar_path, "w", encoding="utf-8") as f:
        f.write(content)


def build_attribution_record(
    filename: str,
    file_title: str,
    source_url: str,
    extmetadata: Dict,
) -> Dict[str, str]:
    """
    Build a dictionary suitable for CSV output with stable columns.
    """
    object_name = strip_html(get_meta_value(extmetadata, "ObjectName")) or file_title.split(":", 1)[-1]
    artist = strip_html(get_meta_value(extmetadata, "Artist")) or strip_html(get_meta_value(extmetadata, "Author")) or strip_html(get_meta_value(extmetadata, "Credit"))
    license_short = get_meta_value(extmetadata, "LicenseShortName") or get_meta_value(extmetadata, "License")
    license_url = get_meta_value(extmetadata, "LicenseUrl")
    usage_terms = strip_html(get_meta_value(extmetadata, "UsageTerms"))
    suggested = ""
    if artist and license_short:
        if license_url:
            suggested = f"“{object_name}” by {artist} is licensed under {license_short} ({license_url}) via Wikimedia Commons."
        else:
            suggested = f"“{object_name}” by {artist} is licensed under {license_short} via Wikimedia Commons."
    elif license_short:
        if license_url:
            suggested = f"“{object_name}” is licensed under {license_short} ({license_url}) via Wikimedia Commons."
        else:
            suggested = f"“{object_name}” is licensed under {license_short} via Wikimedia Commons."

    return {
        "filename": filename,
        "title": object_name,
        "author": artist or "",
        "license_short": license_short or "",
        "license_url": license_url or "",
        "usage_terms": usage_terms or "",
        "source_url": source_url,
        "suggested_attribution": suggested,
    }


def write_category_csv(category_dir: Path, rows: List[Dict[str, str]]) -> None:
    """
    Append rows to ATTRIBUTION.csv in the category directory; create with header if missing.
    """
    if not rows:
        return
    csv_path = category_dir / "ATTRIBUTION.csv"
    fieldnames = [
        "filename",
        "title",
        "author",
        "license_short",
        "license_url",
        "usage_terms",
        "source_url",
        "suggested_attribution",
    ]
    file_exists = csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def append_failure_record(csv_path: Path, record: Dict[str, str]) -> None:
    """
    Append a single failure/skip record to FAILED_DOWNLOADS.csv (create with header if needed).
    Columns:
      - search_term: The original search term for which this image was processed
      - file_title: The Wikimedia file title (e.g., File:Example.jpg), if known
      - source_url: The resolved direct file URL, if known
      - reason: Short machine-friendly reason (e.g., no_metadata, no_url, non_image_mime, non_image_title, download_error)
      - detail: Human-readable extra info (e.g., MIME type, HTTP error message)
    """
    fieldnames = ["search_term", "file_title", "source_url", "reason", "detail"]
    file_exists = csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(record)


def chunked(iterable: Iterable[str], size: int) -> Iterable[List[str]]:
    buf: List[str] = []
    for item in iterable:
        buf.append(item)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def query_image_metadata(session: requests.Session, file_titles: List[str]) -> Dict[str, Dict]:
    """
    Queries imageinfo and extmetadata for the given File: titles.
    Returns a map: normalized_title -> info dict including 'url' and 'extmetadata'.
    """
    results: Dict[str, Dict] = {}
    # MediaWiki limits the number of titles per request; use 50 per batch for safety
    for batch in chunked(file_titles, 50):
        params = {
            "action": "query",
            "prop": "imageinfo",
            "titles": "|".join(batch),
            "iiprop": "url|size|mime|extmetadata",
            "format": "json",
            "formatversion": 2,
            "utf8": 1,
            "redirects": 1,
            "maxlag": 5,
        }
        resp = http_get(session, WIKIPEDIA_API, params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        pages = data.get("query", {}).get("pages", []) or []
        for page in pages:
            title = page.get("title")
            imageinfo = page.get("imageinfo") or []
            if not title or not imageinfo:
                continue
            info = imageinfo[0]
            results[title] = {
                "title": title,
                "url": info.get("url"),
                "mime": info.get("mime"),
                "size": {"width": info.get("width"), "height": info.get("height")},
                "extmetadata": info.get("extmetadata", {}),
            }
        time.sleep(REQUEST_DELAY_S)  # be polite
    return results


def safe_folder_name(name: str) -> str:
    """
    Create a filesystem-safe folder name from arbitrary text.
    """
    name = name.strip()
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name)
    name = re.sub(r"\s+", " ", name)
    name = name.strip(" .")
    return name or "untitled"


def get_meta_value(extmetadata: Dict, key: str, default: str = "") -> str:
    val = extmetadata.get(key)
    if isinstance(val, dict):
        return val.get("value", default) or default
    if isinstance(val, str):
        return val
    return default


def categorize_license(extmetadata: Dict) -> Tuple[str, str]:
    """
    Determine a high-level license category and a human-readable label.
    Categories:
      - public_domain
      - cc_by
      - cc_by_sa
      - other_cc
      - restricted_nonfree
      - unknown
    """
    license_code = get_meta_value(extmetadata, "License").lower()
    license_short = get_meta_value(extmetadata, "LicenseShortName").lower()
    usage_terms = get_meta_value(extmetadata, "UsageTerms").lower()
    restrictions = get_meta_value(extmetadata, "Restrictions").lower()
    attribution_required = get_meta_value(extmetadata, "AttributionRequired").lower()

    # Public domain / CC0 fast path
    if "public domain" in license_short or license_code in {"pd", "cc-zero"} or "cc0" in license_short:
        return "public_domain", "Public Domain / CC0"

    # Non-free indicators
    nonfree_markers = ["nonfree", "non-free", "fair use"]
    if (
        any(x in usage_terms for x in nonfree_markers)
        or any(x in restrictions for x in nonfree_markers)
        or license_code in {"unknown", "arr"}  # all rights reserved or unknown
    ):
        return "restricted_nonfree", "Restricted / Non-free"

    # Creative Commons breakdown
    if license_code.startswith("cc-by-sa") or "cc by-sa" in license_short:
        return "cc_by_sa", "Creative Commons BY-SA"
    if license_code.startswith("cc-by") or ("cc by" in license_short and "sa" not in license_short):
        return "cc_by", "Creative Commons BY"
    if license_code.startswith("cc-") or license_short.startswith("cc "):
        return "other_cc", "Creative Commons (Other)"

    # Attribution required but license unknown
    if attribution_required == "true":
        return "other_cc", "Creative Commons (Attribution)"

    # Fallback
    if license_short or license_code:
        return "unknown", f"Unknown ({license_short or license_code})"
    return "unknown", "Unknown"


def download_file(session: requests.Session, url: str, dest_path: Path) -> None:
    with http_get(session, url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def make_output_paths(base_dir: Path, search_term: str, category_key: str) -> Path:
    root = base_dir / safe_folder_name(search_term)
    category_dir = root / category_key
    ensure_directory(category_dir)
    return category_dir


def read_config_output_dir() -> Optional[str]:
    """
    Reads output_dir from a simple INI config file. Supported locations:
      - ./.wikipedia_image_downloader.ini
      - ~/.wikipedia_image_downloader.ini
      - ~/.config/wikipedia_image_downloader/config.ini
    INI format:
      [settings]
      output_dir = /absolute/path
    """
    candidates = [
        Path.cwd() / ".wikipedia_image_downloader.ini",
        Path.home() / ".wikipedia_image_downloader.ini",
        Path.home() / ".config" / "wikipedia_image_downloader" / "config.ini",
    ]
    parser = configparser.ConfigParser()
    for cfg_path in candidates:
        try:
            if not cfg_path.exists():
                continue
            parser.read(cfg_path)
            if parser.has_section("settings"):
                out = parser.get("settings", "output_dir", fallback="").strip()
                if out:
                    return out
        except Exception:
            # Ignore malformed configs and try next
            continue
    return None


def resolve_output_dir(cli_output: Optional[str]) -> Path:
    """
    Resolution order:
      1) CLI --output
      2) ENV WIKI_IMG_OUTPUT_DIR
      3) Config file 'output_dir'
      4) Current directory '.'
    """
    # 1) CLI
    if cli_output:
        return Path(cli_output).expanduser().resolve()
    # 2) ENV
    env_out = os.environ.get("WIKI_IMG_OUTPUT_DIR", "").strip()
    if env_out:
        return Path(env_out).expanduser().resolve()
    # 3) Config
    cfg_out = read_config_output_dir()
    if cfg_out:
        return Path(cfg_out).expanduser().resolve()
    # 4) Default
    return Path(".").resolve()


def infer_filename_from_url(url: str) -> str:
    """
    Extract and decode the filename from a URL.
    URL-decodes the name so %2C becomes comma, %C3%B3 becomes ó, etc.
    Also sanitizes for filesystem safety.
    """
    name = url.split("/")[-1]
    name = name.split("?")[0]
    if not name:
        return "file"
    # URL-decode to get actual characters (e.g., %2C -> comma, %C3%B3 -> ó)
    name = unquote(name)
    # Sanitize for filesystem: remove/replace characters that are problematic
    # Keep most Unicode characters but remove truly problematic ones
    # Replace characters that are invalid on Windows/macOS: \ / : * ? " < > |
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    # Collapse multiple underscores
    name = re.sub(r'_+', '_', name)
    return name or "file"

def maybe_convert_svg_to_png(src_svg_path: Path, png_width: int) -> Optional[Path]:
    """
    If file is an SVG, convert to PNG at specified width while preserving transparency.
    Returns the PNG path if created, otherwise None.
    """
    if src_svg_path.suffix.lower() != ".svg":
        return None
    # Lazy import so missing system cairo doesn't break the whole script
    try:
        import cairosvg  # type: ignore
    except Exception as e:
        global _SVG_IMPORT_FAILED_WARNED
        if not _SVG_IMPORT_FAILED_WARNED:
            print("SVG conversion unavailable: Cairo/cairosvg not usable. Install system Cairo (e.g., brew install cairo pango).", file=sys.stderr)
            _SVG_IMPORT_FAILED_WARNED = True
        return None
    png_path = src_svg_path.with_suffix(".png")
    try:
        with open(src_svg_path, "rb") as f:
            svg_bytes = f.read()
        cairosvg.svg2png(bytestring=svg_bytes, write_to=str(png_path), output_width=png_width)
        return png_path
    except Exception as e:
        print(f"  SVG conversion failed for {src_svg_path.name}: {e}", file=sys.stderr)
        return None

def http_get(
    session: requests.Session,
    url: str,
    params: Optional[Dict] = None,
    stream: bool = False,
    timeout: int = 30,
) -> requests.Response:
    """
    GET with retries, exponential backoff and jitter. Respects Retry-After.
    Retries on 429 and common 5xx errors.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, params=params, stream=stream, timeout=timeout)
            if resp.status_code < 400:
                return resp
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                sleep_s = None
                if retry_after:
                    try:
                        sleep_s = float(retry_after)
                    except Exception:
                        sleep_s = None
                if sleep_s is None:
                    sleep_s = RETRY_BACKOFF_S * (2 ** (attempt - 1)) + random.uniform(0, 0.25)
                time.sleep(sleep_s)
                continue
            if resp.status_code in (500, 502, 503, 504):
                sleep_s = RETRY_BACKOFF_S * (2 ** (attempt - 1)) + random.uniform(0, 0.25)
                time.sleep(sleep_s)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            last_exc = e
            sleep_s = RETRY_BACKOFF_S * (2 ** (attempt - 1)) + random.uniform(0, 0.25)
            time.sleep(sleep_s)
    if last_exc:
        raise last_exc
    raise RuntimeError("http_get exhausted retries without exception")

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Download top images from a Wikipedia page grouped by license.")
    parser.add_argument("queries", nargs="+", help="One or more search terms to find Wikipedia pages")
    parser.add_argument("--limit", type=int, default=10, help="Max number of images to download (default: 10)")
    parser.add_argument("--output", type=str, default=None, help="Output directory. If omitted, use ENV/CONFIG or current directory.")
    parser.add_argument("--user-agent", type=str, default=DEFAULT_USER_AGENT, help="Custom HTTP User-Agent")
    parser.add_argument("--delay", type=float, default=0.3, help="Politeness delay between requests (seconds). Default: 0.3")
    parser.add_argument("--max-retries", type=int, default=5, help="Max HTTP retries on 429/5xx. Default: 5")
    parser.add_argument("--retry-backoff", type=float, default=1.0, help="Base backoff seconds for retries. Default: 1.0")
    parser.add_argument("--no-svg-to-png", action="store_true", help="Disable SVG to PNG conversion (enabled by default).")
    parser.add_argument("--png-width", type=int, default=3000, help="PNG width for SVG conversion (default: 3000).")
    parser.add_argument("--prefer-recent", action="store_true", help="Prioritize newer images first when year can be inferred.")
    parser.add_argument("--no-historical-priority", action="store_true", help="Disable older-first reordering; keep source order.")
    args = parser.parse_args(argv)

    # Sanitize queries: allow users to separate with commas in shell inputs
    args.queries = [q.strip().strip(",") for q in args.queries if q.strip().strip(",")]

    # Apply runtime tunables
    global REQUEST_DELAY_S, MAX_RETRIES, RETRY_BACKOFF_S, SVG_TO_PNG, SVG_PNG_WIDTH
    REQUEST_DELAY_S = max(0.0, float(args.delay))
    MAX_RETRIES = max(1, int(args.max_retries))
    RETRY_BACKOFF_S = max(0.0, float(args.retry_backoff))
    SVG_TO_PNG = not bool(args.no_svg_to_png)
    SVG_PNG_WIDTH = max(1, int(args.png_width))

    output_dir = resolve_output_dir(args.output)
    ensure_directory(output_dir)
    # Global failures log (independent of search term)
    global_failed_csv_path = output_dir / "FAILED_DOWNLOADS.csv"

    session = build_http_session(args.user_agent)

    any_success = False
    for term_index, query in enumerate(args.queries, start=1):
        if term_index > 1:
            print("")  # spacer between terms
        print(f"[{term_index}/{len(args.queries)}] Searching Wikipedia for: {query}")
        page = search_wikipedia_page(session, query)
        if not page:
            print("No Wikipedia results found.", file=sys.stderr)
            continue
        pageid = page["pageid"]
        title = page["title"]
        print(f"Found page: {title} (pageid={pageid})")

        # Get images from content only; if none, fallback to parse/images filtered
        all_images = get_content_images(session, pageid)
        if not all_images:
            fallback = filter_out_ui_icons(get_page_images(session, pageid))
            if fallback:
                print(f"No content-anchored images found; falling back to {len(fallback)} page images (filtered).")
                all_images = fallback
            else:
                print("No images found in article content.", file=sys.stderr)
                continue
        print(f"Found {len(all_images)} file links; downloading up to {args.limit} images.")

        # Query metadata for all candidates so we can filter to images and still meet the limit
        metadata_map = query_image_metadata(session, all_images)

        # Reorder according to preferences
        if args.no_historical_priority and not args.prefer_recent:
            ordered_titles = all_images
            print("Keeping source order (no historical priority).")
        elif args.prefer_recent:
            ordered_titles = reorder_by_recent_priority(all_images, metadata_map)
            print("Prioritizing recent images first (newer years preferred).")
        else:
            ordered_titles = reorder_by_historical_priority(all_images, metadata_map)
            cutoff_info = datetime.datetime.now().year - 30
            print(f"Prioritizing historical images first (<= {cutoff_info}).")

        # Prepare root directory for this search term
        search_root = output_dir / safe_folder_name(query)
        ensure_directory(search_root)

        # Info file summarizing categories
        summary_lines: List[str] = []
        counts_by_cat: Dict[str, int] = {}
        attribution_rows_by_cat: Dict[str, List[Dict[str, str]]] = {}
        category_dirs: Dict[str, Path] = {}

        # Download files grouped by license category until limit reached
        downloaded_count = 0
        for idx, title_key in enumerate(ordered_titles, start=1):
            if downloaded_count >= args.limit:
                break
            # Skip blacklisted basenames
            bl_match = match_blacklist_pattern(title_key)
            if bl_match:
                print(f"[{idx}/{len(all_images)}] Skipping {title_key}: blacklisted pattern '{bl_match}'.")
                try:
                    append_failure_record(
                        global_failed_csv_path,
                        {
                            "search_term": query,
                            "file_title": title_key,
                            "source_url": "",
                            "reason": "blacklist_pattern",
                            "detail": bl_match,
                        },
                    )
                except Exception:
                    pass
                continue
            meta = metadata_map.get(title_key)
            if not meta:
                print(f"[{idx}/{len(all_images)}] Skipping {title_key}: no metadata.")
                try:
                    append_failure_record(
                        global_failed_csv_path,
                        {
                            "search_term": query,
                            "file_title": title_key,
                            "source_url": "",
                            "reason": "no_metadata",
                            "detail": "",
                        },
                    )
                except Exception:
                    pass
                continue
            url = meta.get("url")
            if not url:
                print(f"[{idx}/{len(all_images)}] Skipping {title_key}: no URL.")
                try:
                    append_failure_record(
                        global_failed_csv_path,
                        {
                            "search_term": query,
                            "file_title": title_key,
                            "source_url": "",
                            "reason": "no_url",
                            "detail": "",
                        },
                    )
                except Exception:
                    pass
                continue
            # Enforce images only by MIME and by title heuristic
            mime = meta.get("mime")
            if not is_image_mime(mime) or is_probably_non_image_title(title_key):
                # Log skip reason for transparency
                try:
                    if not is_image_mime(mime):
                        append_failure_record(
                            global_failed_csv_path,
                            {
                                "search_term": query,
                                "file_title": title_key,
                                "source_url": url or "",
                                "reason": "non_image_mime",
                                "detail": str(mime or ""),
                            },
                        )
                    elif is_probably_non_image_title(title_key):
                        append_failure_record(
                            global_failed_csv_path,
                            {
                                "search_term": query,
                                "file_title": title_key,
                                "source_url": url or "",
                                "reason": "non_image_title",
                                "detail": "",
                            },
                        )
                except Exception:
                    pass
                continue
            extmetadata = meta.get("extmetadata", {})
            # Skip symbolic SVGs (flags, coats of arms, signatures); continue scanning for alternatives
            if is_symbolic_svg(title_key, mime, extmetadata):
                try:
                    append_failure_record(
                        global_failed_csv_path,
                        {
                            "search_term": query,
                            "file_title": title_key,
                            "source_url": url or "",
                            "reason": "symbolic_svg",
                            "detail": str(mime or ""),
                        },
                    )
                except Exception:
                    pass
                continue
            category_key, category_label = categorize_license(extmetadata)
            category_dir = make_output_paths(output_dir, query, category_key)

            filename = infer_filename_from_url(url)
            dest_path = category_dir / filename
            # If destination already exists, skip download
            if dest_path.exists():
                print(f"[{downloaded_count+1}/{args.limit}] Skipping {title_key}: already exists at {category_key}/{dest_path.name}")
                try:
                    append_failure_record(
                        global_failed_csv_path,
                        {
                            "search_term": query,
                            "file_title": title_key,
                            "source_url": url or "",
                            "reason": "already_exists",
                            "detail": dest_path.name,
                        },
                    )
                except Exception:
                    pass
                continue

            print(f"[{downloaded_count+1}/{args.limit}] Downloading {title_key} -> {category_key}/{dest_path.name}")
            try:
                download_file(session, url, dest_path)
            except Exception as e:
                print(f"  Failed: {e}", file=sys.stderr)
                # Record failure
                try:
                    append_failure_record(
                        global_failed_csv_path,
                        {
                            "search_term": query,
                            "file_title": title_key,
                            "source_url": url or "",
                            "reason": "download_error",
                            "detail": str(e),
                        },
                    )
                except Exception:
                    pass
                continue
            # Count and track successful download
            counts_by_cat[category_key] = counts_by_cat.get(category_key, 0) + 1
            category_dirs.setdefault(category_key, category_dir)
            # Optional: convert SVG to PNG
            if SVG_TO_PNG and (mime == "image/svg+xml" or dest_path.suffix.lower() == ".svg"):
                png_path = maybe_convert_svg_to_png(dest_path, SVG_PNG_WIDTH)
                if png_path:
                    print(f"  Converted SVG to PNG ({SVG_PNG_WIDTH}px): {png_path.name}")
            # For non-public-domain, write an attribution sidecar
            if category_key != "public_domain":
                try:
                    attr_text = build_attribution_text(title_key, url, extmetadata, category_key)
                    write_attribution_sidecar(dest_path, attr_text)
                    # Also collect CSV row for this category
                    row = build_attribution_record(dest_path.name, title_key, url, extmetadata)
                    attribution_rows_by_cat.setdefault(category_key, []).append(row)
                except Exception as e:
                    print(f"  Failed to write attribution for {dest_path.name}: {e}", file=sys.stderr)

            # Append a summary line
            license_short = get_meta_value(extmetadata, "LicenseShortName") or "Unknown"
            license_url = get_meta_value(extmetadata, "LicenseUrl") or ""
            summary_lines.append(f"{dest_path.name}\t{category_key}\t{license_short}\t{license_url}\t{url}")
            downloaded_count += 1

        # Write summary file
        summary_path = search_root / "DOWNLOAD_SUMMARY.tsv"
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("filename\tcategory\tlicense_short\tlicense_url\tsource_url\n")
            for line in summary_lines:
                f.write(line + "\n")

        # Report counts
        print("Done.")
        print("Images by category:")
        for k, v in sorted(counts_by_cat.items()):
            print(f"  - {k}: {v}")
        print(f"Saved summary: {summary_path}")
        # Write per-category CSVs for non-public-domain categories
        for cat_key, rows in sorted(attribution_rows_by_cat.items()):
            try:
                cat_dir = category_dirs.get(cat_key) or make_output_paths(output_dir, query, cat_key)
                write_category_csv(cat_dir, rows)
                print(f"Wrote/updated attribution CSV: {cat_dir / 'ATTRIBUTION.csv'}")
            except Exception as e:
                print(f"  Failed to write CSV for {cat_key}: {e}", file=sys.stderr)
        any_success = any_success or bool(summary_lines)
        time.sleep(REQUEST_DELAY_S)  # small pause between terms

    return 0 if any_success else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)


