#!/usr/bin/env python3
"""
srt_entities.py

Parse an SRT transcript, extract entities (people, places, concepts, events) per cue
using an LLM, and produce a JSON map of entities to their occurrences and cue indices.

Usage:
  python tools/srt_entities.py --srt path/to/timeline.srt --out entities_map.json \
    --provider openai --model gpt-4o-mini

Env (OpenAI-compatible):
  - OPENAI_API_KEY (required for provider=openai)
  - OPENAI_API_BASE (optional; defaults to https://api.openai.com/v1)

Env (Anthropic):
  - ANTHROPIC_API_KEY (required for provider=anthropic)

Env (Ollama):
  - OLLAMA_HOST (default http://127.0.0.1:11434)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Auto-load API keys from config file
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: F401

import requests
from dotenv import load_dotenv
from requests.exceptions import HTTPError, ConnectionError, Timeout

load_dotenv()

# Retry configuration for transient API errors
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds, will use exponential backoff

RELATIVE_TIME_PREFIX_RE = re.compile(r"^\s*(\d+\s*(years?|months?|weeks?|days?)\s*(later|after|before|since)|\d{1,3}(st|nd|rd|th)\s+anniversary(?:\s+of)?\s+)", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")
EVENT_KEYWORDS_RE = re.compile(r"\b(war|revolution|revolt|rebellion|uprising|coup|election|elections|referendum|treaty|accord|agreement|crisis|massacre|genocide|independence|reform|protest|protests)\b", re.IGNORECASE)

@dataclass
class SrtCue:
    index: int
    start: str  # 'HH:MM:SS,mmm'
    end: str
    text: str


def _format_hhmmss_frames_to_srt(hh: str, mm: str, ss: str, ff: str, fps: float) -> str:
    total_seconds = int(hh) * 3600 + int(mm) * 60 + int(ss) + (int(ff) / max(1.0, float(fps)))
    ms = int(round((total_seconds - int(total_seconds)) * 1000))
    total_seconds_int = int(total_seconds)
    h = total_seconds_int // 3600
    m = (total_seconds_int % 3600) // 60
    s = total_seconds_int % 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _strip_speaker_lines(text_lines: List[str]) -> List[str]:
    """
    Remove lines like 'Speaker 2' that are common in some transcript exports.
    """
    cleaned: List[str] = []
    for line in text_lines:
        if re.match(r"^\s*Speaker\s+\d+\s*$", line, flags=re.IGNORECASE):
            continue
        cleaned.append(line)
    return cleaned


def parse_srt(path: str, fps: float = 25.0) -> List[SrtCue]:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    blocks = re.split(r"\n\s*\n", content.strip(), flags=re.MULTILINE)
    cues: List[SrtCue] = []
    idx_counter = 1
    for block in blocks:
        raw_lines = block.splitlines()
        # Keep blank lines inside block minimal; strip BOMs
        lines = [ln.strip("\ufeff") for ln in raw_lines if ln.strip() != "" or ln.strip() == "0"]
        if not lines:
            continue
        # Case 1: Standard SRT with numeric index on first line
        if re.match(r"^\d+\s*$", lines[0]):
            try:
                idx = int(lines[0].strip())
                times = lines[1]
                m = re.match(r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})", times)
                if not m:
                    # Try VTT-like with '.'
                    m = re.match(r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})", times)
                if not m:
                    # Try bracketed HH:MM:SS:FF - HH:MM:SS:FF on second line
                    m2 = re.match(r"^\[?(\d{2}):(\d{2}):(\d{2}):(\d{2})\s*-\s*(\d{2}):(\d{2}):(\d{2}):(\d{2})\]?$", times)
                    if not m2:
                        raise ValueError("No time format matched")
                    start = _format_hhmmss_frames_to_srt(m2.group(1), m2.group(2), m2.group(3), m2.group(4), fps)
                    end = _format_hhmmss_frames_to_srt(m2.group(5), m2.group(6), m2.group(7), m2.group(8), fps)
                else:
                    start = m.group(1).replace(".", ",")
                    end = m.group(2).replace(".", ",")
                text_lines = _strip_speaker_lines(lines[2:])
                text = "\n".join(text_lines).strip()
                cues.append(SrtCue(index=idx, start=start, end=end, text=text))
                continue
            except Exception:
                # Fall through to other patterns below
                pass

        # Case 2: First line is a time range (SRT without index)
        m = re.match(r"^(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})$", lines[0])
        if m:
            start = m.group(1).replace(".", ",")
            end = m.group(2).replace(".", ",")
            text_lines = _strip_speaker_lines(lines[1:])
            text = "\n".join(text_lines).strip()
            cues.append(SrtCue(index=idx_counter, start=start, end=end, text=text))
            idx_counter += 1
            continue

        # Case 3: Bracketed HH:MM:SS:FF - HH:MM:SS:FF (no numeric index)
        m2 = re.match(r"^\[?(\d{2}):(\d{2}):(\d{2}):(\d{2})\s*-\s*(\d{2}):(\d{2}):(\d{2}):(\d{2})\]?$", lines[0])
        if m2:
            start = _format_hhmmss_frames_to_srt(m2.group(1), m2.group(2), m2.group(3), m2.group(4), fps)
            end = _format_hhmmss_frames_to_srt(m2.group(5), m2.group(6), m2.group(7), m2.group(8), fps)
            text_lines = _strip_speaker_lines(lines[1:])
            text = "\n".join(text_lines).strip()
            cues.append(SrtCue(index=idx_counter, start=start, end=end, text=text))
            idx_counter += 1
            continue
        # Unrecognized block; skip
    return cues


def call_llm_extract(
    provider: str,
    model: str,
    text: str,
    subject: Optional[str],
    openai_api_key: Optional[str],
    openai_api_base: Optional[str],
    ollama_host: Optional[str],
    anthropic_api_key: Optional[str] = None,
) -> Dict[str, List[str]]:
    """
    Returns a dict with keys: people, places, concepts, events -> list[str]
    Optionally includes 'primary' (string) naming the most salient entity in the cue.
    """
    system_prompt = (
        "You extract named entities from transcript cues. Return strict JSON with keys: "
        "people, places, concepts, events, primary. Each entity in the arrays must be an object with 'name' (the surface form as it appears) "
        "and 'canonical' (the full, unambiguous Wikipedia-style name). Example: "
        '{"name": "Obama", "canonical": "Barack Obama"}, {"name": "JFK", "canonical": "John F. Kennedy"}. '
        "'primary' must be a single string naming the canonical form of the one entity the cue is most about, "
        "and it must match a canonical in one of the arrays; if none, set it to an empty string. No extra keys. "
        "If none, use empty arrays. "
        "Vagueness rule: If an entity is too vague to be useful on its own relative to the transcript's subject "
        "(e.g., an event that is just a year like '1947', or 'elections' with only a year and no country, or a "
        "movement/revolution with no geographic qualifier), then append the transcript subject to the canonical name. "
        "Example: '1947 elections' -> canonical '1947 elections Venezuela' when the subject is 'Venezuela'. "
        "Important: Prefer canonical names likely to have a standalone Wikipedia page. Do NOT output relative-time phrases "
        "such as '100 years later the Federal War in Venezuela'; instead, extract the underlying canonical entity name, e.g., "
        "'Federal War (Venezuela)' or 'Federal War Venezuela'. Avoid generic temporal descriptors ('years later', 'decades ago')."
    )
    subject_line = f"Transcript subject/context: {subject}\n" if subject else ""
    user_prompt = f"{subject_line}Transcript cue:\n{text}\n\nReturn JSON only."

    if provider == "openai":
        base = openai_api_base or "https://api.openai.com/v1"
        headers = {"Authorization": f"Bearer {openai_api_key}", "Content-Type": "application/json"}
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = requests.post(f"{base}/chat/completions", headers=headers, json=body, timeout=60)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                break
            except HTTPError as e:
                if e.response is not None and e.response.status_code in RETRY_STATUS_CODES and attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    print(f"    [Retry {attempt+1}/{MAX_RETRIES}] {e.response.status_code} error, waiting {delay:.1f}s...", file=sys.stderr)
                    time.sleep(delay)
                    last_error = e
                else:
                    raise
            except (ConnectionError, Timeout) as e:
                if attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    print(f"    [Retry {attempt+1}/{MAX_RETRIES}] Connection error, waiting {delay:.1f}s...", file=sys.stderr)
                    time.sleep(delay)
                    last_error = e
                else:
                    raise
        else:
            if last_error:
                raise last_error
    elif provider == "anthropic":
        headers = {
            "x-api-key": anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = requests.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=headers, json=body, timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                # Anthropic returns content as a list of blocks
                content_blocks = data.get("content", [])
                content = "".join(
                    block.get("text", "") for block in content_blocks
                    if block.get("type") == "text"
                )
                break
            except HTTPError as e:
                if e.response is not None and e.response.status_code in RETRY_STATUS_CODES and attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    print(f"    [Retry {attempt+1}/{MAX_RETRIES}] {e.response.status_code} error, waiting {delay:.1f}s...", file=sys.stderr)
                    time.sleep(delay)
                    last_error = e
                else:
                    raise
            except (ConnectionError, Timeout) as e:
                if attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    print(f"    [Retry {attempt+1}/{MAX_RETRIES}] Connection error, waiting {delay:.1f}s...", file=sys.stderr)
                    time.sleep(delay)
                    last_error = e
                else:
                    raise
        else:
            if last_error:
                raise last_error
    elif provider == "ollama":
        host = ollama_host or "http://127.0.0.1:11434"
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {"temperature": 0.2},
        }
        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = requests.post(f"{host}/api/chat", json=body, timeout=120)
                resp.raise_for_status()
                data = resp.json()
                content = data.get("message", {}).get("content", "")
                break
            except HTTPError as e:
                if e.response is not None and e.response.status_code in RETRY_STATUS_CODES and attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    print(f"    [Retry {attempt+1}/{MAX_RETRIES}] {e.response.status_code} error, waiting {delay:.1f}s...", file=sys.stderr)
                    time.sleep(delay)
                    last_error = e
                else:
                    raise
            except (ConnectionError, Timeout) as e:
                if attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    print(f"    [Retry {attempt+1}/{MAX_RETRIES}] Connection error, waiting {delay:.1f}s...", file=sys.stderr)
                    time.sleep(delay)
                    last_error = e
                else:
                    raise
        else:
            if last_error:
                raise last_error
    else:
        raise ValueError("Unsupported provider. Use 'openai', 'anthropic', or 'ollama'.")

    # Extract JSON from content
    match = re.search(r"\{[\s\S]*\}", content)
    if not match:
        return {"people": [], "places": [], "concepts": [], "events": [], "primary": ""}
    try:
        parsed = json.loads(match.group(0))
        # Preserve both old (string) and new (object with name/canonical) formats
        # _parse_entity_list handles both formats downstream
        result = {
            "people": parsed.get("people", []) if isinstance(parsed.get("people"), list) else [],
            "places": parsed.get("places", []) if isinstance(parsed.get("places"), list) else [],
            "concepts": parsed.get("concepts", []) if isinstance(parsed.get("concepts"), list) else [],
            "events": parsed.get("events", []) if isinstance(parsed.get("events"), list) else [],
            "primary": parsed.get("primary") if isinstance(parsed.get("primary", ""), str) else "",
        }
        return result
    except Exception:
        return {"people": [], "places": [], "concepts": [], "events": [], "primary": ""}


def _parse_entity_list(raw_list: list) -> List[Tuple[str, str]]:
    """Parse entity list, handling both old (string) and new (object) formats.

    Returns list of (surface_name, canonical_name) tuples.
    """
    results = []
    for item in raw_list:
        if isinstance(item, str):
            name = item.strip()
            if name:
                results.append((name, name))  # canonical = name for old format
        elif isinstance(item, dict):
            name = (item.get("name") or "").strip()
            canonical = (item.get("canonical") or name).strip()
            if name:
                results.append((name, canonical if canonical else name))
    return results


def _srt_time_to_seconds(tc: str) -> float:
    """
    Convert 'HH:MM:SS,ms' to float seconds.
    """
    m = re.match(r"^\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*$", tc)
    if not m:
        return 0.0
    h = int(m.group(1)); mi = int(m.group(2)); s = int(m.group(3)); ms = int(m.group(4))
    return h * 3600 + mi * 60 + s + ms / 1000.0

def _normalize_entity_name(name: str, kind: str, subject: Optional[str]) -> str:
    """
    Basic normalization of extracted names:
      - strip leading relative-time phrases (e.g., '100 years later ')
      - collapse whitespace and trim punctuation
    """
    s = name or ""
    s = RELATIVE_TIME_PREFIX_RE.sub("", s)
    s = WHITESPACE_RE.sub(" ", s)
    s = s.strip(" \t\r\n-–—")
    return s

def _looks_like_wikipedia_entity(name: str, kind: str) -> bool:
    """
    Heuristic filter for plausibility as a standalone Wikipedia-like entity.
    """
    if not name:
        return False
    txt = name.strip()
    if not txt:
        return False
    if RELATIVE_TIME_PREFIX_RE.match(txt):
        return False
    # avoid pure punctuation or empty alphanumerics
    if len(re.sub(r"[^A-Za-z0-9]+", "", txt)) == 0:
        return False
    low = txt.lower()
    if any(k in low for k in ["years later", "years earlier", "years ago", "decades", "centuries", "months later", "days later"]):
        return False
    if kind in ("events", "concepts"):
        if EVENT_KEYWORDS_RE.search(txt):
            return True
        # allow proper-noun-like strings
        return bool(re.search(r"[A-Z].+", txt))
    return True


def _merge_by_canonical(
    entities: Dict[str, Dict],
    canonical: str,
    surface_name: str,
    kind: str,
    occurrence: Dict,
) -> None:
    """Add occurrence to entity, merging by canonical name.

    Creates a new entity entry if canonical doesn't exist, otherwise merges
    the occurrence and adds the surface_name as an alias.
    """
    if canonical not in entities:
        entities[canonical] = {
            "entity_type": kind,
            "images": [],
            "occurrences": [],
            "aliases": set(),
        }
    entity = entities[canonical]
    entity["occurrences"].append(occurrence)
    entity["aliases"].add(surface_name)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Extract entities per SRT cue and emit entities_map.json")
    parser.add_argument("--srt", required=True, help="Path to SRT transcript")
    parser.add_argument("--out", required=True, help="Output JSON path (entities_map.json)")
    parser.add_argument("--provider", choices=["openai", "anthropic", "ollama"], default="openai")
    parser.add_argument("--model", required=True, help="Model name (e.g., gpt-4o-mini or llama3)")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay between LLM calls (seconds)")
    parser.add_argument("--fps", type=float, default=25.0, help="FPS for HH:MM:SS:FF timecodes (default: 25.0)")
    parser.add_argument("--subject", type=str, default=None, help="Transcript subject (e.g., 'Venezuela'). If omitted, inferred from dominant place mentions.")
    args = parser.parse_args(argv)

    cues = parse_srt(args.srt, fps=args.fps)
    if not cues:
        print("No cues parsed from SRT.", file=sys.stderr)
        return 2

    openai_api_key = os.environ.get("OPENAI_API_KEY")
    openai_api_base = os.environ.get("OPENAI_API_BASE")
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
    ollama_host = os.environ.get("OLLAMA_HOST")

    total = len(cues)
    entities: Dict[str, Dict] = {}
    # Track place frequency across all mentions (for subject inference)
    place_counts: Dict[str, int] = {}
    # 5-second window gating
    window_start_s: Optional[float] = None
    emitted_primary_in_window: bool = False
    emitted_names_in_window: set = set()

    for idx, cue in enumerate(cues, start=1):
        print(f"[{idx}/{total}] Extracting entities for {cue.start} --> {cue.end}", flush=True)
        ent = call_llm_extract(
            provider=args.provider,
            model=args.model,
            text=cue.text,
            subject=args.subject,
            openai_api_key=openai_api_key,
            openai_api_base=openai_api_base,
            ollama_host=ollama_host,
            anthropic_api_key=anthropic_api_key,
        )
        # Update place frequency regardless of throttling (use canonical names)
        for surface, canonical in _parse_entity_list(ent.get("places") or []):
            nn = _normalize_entity_name(canonical, "places", args.subject)
            if nn:
                place_counts[nn] = place_counts.get(nn, 0) + 1

        # Reset window if needed
        t_s = _srt_time_to_seconds(cue.start)
        if window_start_s is None or (t_s - window_start_s) >= 5.0:
            window_start_s = t_s
            emitted_primary_in_window = False
            emitted_names_in_window = set()

        # Normalize and filter all candidates in this cue
        # Map canonical_name -> (kind, surface_name)
        normalized: Dict[str, Tuple[str, str]] = {}
        for kind in ("people", "places", "events", "concepts"):
            for surface, canonical in _parse_entity_list(ent.get(kind) or []):
                nn = _normalize_entity_name(canonical, kind, args.subject)
                if not nn:
                    continue
                if not _looks_like_wikipedia_entity(nn, kind):
                    continue
                if nn not in normalized:
                    normalized[nn] = (kind, surface)

        # Determine primary candidate
        primary_name: Optional[str] = None
        primary_kind: Optional[str] = None
        primary_from_llm = (ent.get("primary") or "").strip() if isinstance(ent.get("primary"), str) else ""
        if primary_from_llm:
            # Try to map to normalized candidates
            # Try all kinds for normalization
            for k in ("people", "places", "events", "concepts"):
                pn = _normalize_entity_name(primary_from_llm, k, args.subject)
                if pn in normalized and _looks_like_wikipedia_entity(pn, normalized[pn][0]):
                    primary_name, primary_kind = pn, normalized[pn][0]
                    break
        if primary_name is None:
            for k in ("people", "places", "events", "concepts"):
                cand = next((nm for nm, (kk, _) in normalized.items() if kk == k), None)
                if cand:
                    primary_name, primary_kind = cand, k
                    break

        # Collect names to emit for this cue: (canonical, surface_name, kind)
        to_emit: List[Tuple[str, str, str]] = []
        if not emitted_primary_in_window and primary_name and (primary_name not in emitted_names_in_window):
            surface = normalized[primary_name][1] if primary_name in normalized else primary_name
            to_emit.append((primary_name, surface, primary_kind or "concepts"))
            emitted_primary_in_window = True
            emitted_names_in_window.add(primary_name)

        # Allow multiple people/places within the same 5s window
        for canonical, (kk, surface) in normalized.items():
            if kk in ("people", "places") and canonical not in emitted_names_in_window:
                to_emit.append((canonical, surface, kk))
                emitted_names_in_window.add(canonical)

        # Append selected occurrences using merge (handles aliases)
        for canonical, surface, knd in to_emit:
            _merge_by_canonical(
                entities,
                canonical,
                surface,
                knd,
                {"timecode": cue.start, "cue_idx": cue.index},
            )

        # Log brief stats
        try:
            pc = len(ent.get("people", []) or [])
            plc = len(ent.get("places", []) or [])
            cc = len(ent.get("concepts", []) or [])
            ec = len(ent.get("events", []) or [])
            print(f"  -> people:{pc} places:{plc} concepts:{cc} events:{ec} | emitted:{len(to_emit)}", flush=True)
        except Exception:
            pass

        time.sleep(max(0.0, args.delay))

    # Determine subject if not provided
    subject = args.subject
    if not subject and place_counts:
        # Choose most frequent place mention
        subject = sorted(place_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

    # Post-process to append subject to vague entities (events/concepts) and merge if needed
    def _is_vague(name: str, kind: str, places_set: set, subj: Optional[str]) -> bool:
        if kind not in ("events", "concepts"):
            return False
        lowered = name.lower()
        # Already contains the subject
        if subj and subj.lower() in lowered:
            return False
        # Contains any known place -> less likely vague
        for p in places_set:
            if p.lower() in lowered:
                return False
        # Year-only or year-led phrases like "1947", "1947 elections"
        if re.fullmatch(r"\d{4}", name.strip()):
            return True
        if re.match(r"\d{4}\b", name.strip()):
            # If it's "YYYY elections" or similar without place
            if re.search(r"\b(election|elections|war|revolution|coup|crisis|protest|uprising|referendum)\b", lowered):
                return True
        # Generic movement/event terms without qualifiers
        if re.search(r"\b(election|elections|war|revolution|movement|uprising|coup|crisis|protest|referendum)\b", lowered):
            # Short names (<= 3 tokens) are more likely vague
            if len(name.strip().split()) <= 3:
                return True
        return False

    if subject:
        places_set = {n for n, v in entities.items() if v.get("entity_type") == "places"}
        new_entities: Dict[str, Dict] = {}
        for name, data in entities.items():
            kind = data.get("entity_type", "")
            if _is_vague(name, kind, places_set, subject):
                new_name = f"{name} {subject}"
            else:
                new_name = name
            # Merge if collision
            if new_name in new_entities:
                # Merge occurrences; keep earliest type if conflict
                new_entities[new_name]["occurrences"].extend(data.get("occurrences", []))
                # Merge aliases
                existing_aliases = new_entities[new_name].get("aliases", set())
                new_aliases = data.get("aliases", set())
                if isinstance(existing_aliases, list):
                    existing_aliases = set(existing_aliases)
                if isinstance(new_aliases, list):
                    new_aliases = set(new_aliases)
                new_entities[new_name]["aliases"] = existing_aliases | new_aliases
                # Images remain combined (both empty at this stage)
                if not new_entities[new_name].get("entity_type"):
                    new_entities[new_name]["entity_type"] = kind
            else:
                aliases = data.get("aliases", set())
                if isinstance(aliases, list):
                    aliases = set(aliases)
                new_entities[new_name] = {
                    "entity_type": kind,
                    "images": data.get("images", []),
                    "occurrences": list(data.get("occurrences", [])),
                    "aliases": aliases,
                }
        entities = new_entities

    # Convert alias sets to sorted lists for JSON serialization
    for name, data in entities.items():
        aliases = data.get("aliases", set())
        if isinstance(aliases, set):
            data["aliases"] = sorted(aliases)

    out = {"entities": entities, "source_srt": os.path.abspath(args.srt)}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Wrote {args.out} with {len(entities)} entities.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)

