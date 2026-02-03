#!/usr/bin/env python3
"""
srt_visual_elements.py

Parse an SRT transcript and extract visual opportunities (statistics, quotes,
processes, comparisons) per cue using an LLM, producing a JSON map suitable
for motion graphics generation.

This complements srt_entities.py by finding visual elements that aren't
named entities but still represent good B-roll opportunities.

Usage:
  python tools/srt_visual_elements.py --srt path/to/timeline.srt --out visual_elements.json

Env:
  - ANTHROPIC_API_KEY (required for provider=anthropic)
  - OPENAI_API_KEY (required for provider=openai)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Auto-load API keys from config file
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: F401

import requests


@dataclass
class SrtCue:
    index: int
    start: str  # 'HH:MM:SS,mmm'
    end: str
    text: str


@dataclass
class VisualElement:
    """A visual opportunity extracted from the transcript."""
    element_id: str
    element_type: str  # statistic, quote, process, comparison
    timecode: str
    cue_idx: int
    source_text: str
    data: Dict[str, Any] = field(default_factory=dict)


def _format_hhmmss_frames_to_srt(hh: str, mm: str, ss: str, ff: str, fps: float) -> str:
    """Convert HH:MM:SS:FF timecode to SRT format HH:MM:SS,mmm."""
    total_seconds = int(hh) * 3600 + int(mm) * 60 + int(ss) + (int(ff) / max(1.0, float(fps)))
    ms = int(round((total_seconds - int(total_seconds)) * 1000))
    total_seconds_int = int(total_seconds)
    h = total_seconds_int // 3600
    m = (total_seconds_int % 3600) // 60
    s = total_seconds_int % 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _strip_speaker_lines(text_lines: List[str]) -> List[str]:
    """Remove lines like 'Speaker 2' that are common in transcript exports."""
    cleaned: List[str] = []
    for line in text_lines:
        if re.match(r"^\s*Speaker\s+\d+\s*$", line, flags=re.IGNORECASE):
            continue
        cleaned.append(line)
    return cleaned


def parse_srt(path: str, fps: float = 25.0) -> List[SrtCue]:
    """Parse SRT file into list of cues."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    blocks = re.split(r"\n\s*\n", content.strip(), flags=re.MULTILINE)
    cues: List[SrtCue] = []
    idx_counter = 1

    for block in blocks:
        raw_lines = block.splitlines()
        lines = [ln.strip("\ufeff") for ln in raw_lines if ln.strip() != "" or ln.strip() == "0"]
        if not lines:
            continue

        # Case 1: Standard SRT with numeric index
        if re.match(r"^\d+\s*$", lines[0]):
            try:
                idx = int(lines[0].strip())
                times = lines[1]
                m = re.match(r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})", times)
                if not m:
                    m = re.match(r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})", times)
                if not m:
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
                pass

        # Case 2: Time range without index
        m = re.match(r"^(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})$", lines[0])
        if m:
            start = m.group(1).replace(".", ",")
            end = m.group(2).replace(".", ",")
            text_lines = _strip_speaker_lines(lines[1:])
            text = "\n".join(text_lines).strip()
            cues.append(SrtCue(index=idx_counter, start=start, end=end, text=text))
            idx_counter += 1
            continue

        # Case 3: Bracketed HH:MM:SS:FF
        m2 = re.match(r"^\[?(\d{2}):(\d{2}):(\d{2}):(\d{2})\s*-\s*(\d{2}):(\d{2}):(\d{2}):(\d{2})\]?$", lines[0])
        if m2:
            start = _format_hhmmss_frames_to_srt(m2.group(1), m2.group(2), m2.group(3), m2.group(4), fps)
            end = _format_hhmmss_frames_to_srt(m2.group(5), m2.group(6), m2.group(7), m2.group(8), fps)
            text_lines = _strip_speaker_lines(lines[1:])
            text = "\n".join(text_lines).strip()
            cues.append(SrtCue(index=idx_counter, start=start, end=end, text=text))
            idx_counter += 1
            continue

    return cues


def call_llm_extract_visuals(
    provider: str,
    model: str,
    text: str,
    context: Optional[str],
    api_key: Optional[str],
    api_base: Optional[str],
) -> Dict[str, Any]:
    """
    Extract visual opportunities from a transcript segment using LLM.

    Returns a dict with keys: numbers, dates, quotes, processes, comparisons
    """
    system_prompt = """You extract visual opportunities from transcript segments for motion graphics.
Return strict JSON with these keys (use empty arrays if none found):

{
  "numbers": [
    {
      "value": "85 of 90",
      "label": "Sepoys who refused",
      "number_type": "ratio|count|percentage|measurement|duration|money",
      "visualization": "pie_chart|counter|bar|icon_array|none",
      "raw_numbers": [85, 90],
      "unit": "sepoys|people|years|feet|etc or null"
    }
  ],
  "dates": [
    {
      "date": "18th April 1857",
      "event": "Scheduled execution",
      "date_type": "specific|period|duration",
      "is_timeline_worthy": true
    }
  ],
  "quotes": [
    {
      "text": "The exact quote text",
      "speaker": "Name or Unknown",
      "quote_type": "historical|defiant|ironic|emotional|explanatory",
      "is_quotable": true
    }
  ],
  "processes": [
    {
      "title": "How X works",
      "steps": ["step 1", "step 2", "step 3"],
      "is_complete": true,
      "visualization": "flowchart|bullet_list|numbered_list|flywheel|timeline|none"
    }
  ],
  "comparisons": [
    {
      "before": "old state or value",
      "after": "new state or value",
      "dimension": "what changed",
      "visualization": "side_by_side|arrow|scale"
    }
  ]
}

IMPORTANT GUIDELINES:

NUMBERS - Be smart about relationships:
- "90 ordered, 85 refused" → ONE number entry: {"value": "85 of 90", "visualization": "pie_chart", "raw_numbers": [85, 90]}
- "40 by 50 feet, 2000 sq ft, 200 people" → ONE number: {"value": "200 people in 2000 sq ft", "visualization": "icon_array"}
- Don't extract bare numbers without meaningful context
- Combine related numbers from the same sentence/thought

DATES - Separate from numbers:
- Historical dates that mark events → dates array
- Durations like "3 weeks" or "54 years" → numbers array with number_type: "duration"

QUOTES - Be selective:
- Only truly quotable, memorable, or historically significant statements
- Must be actual speech or writing, not narrator description
- Skip generic statements like "But there's a miracle" or "He had faith"
- Good quotes: defiant statements, ironic observations, historical declarations
- quote_type helps determine visual treatment

PROCESSES - Sequential actions only:
- Must have clear steps that happened in order
- Skip if just a single action

Return valid JSON only."""

    context_line = f"Video context: {context}\n" if context else ""
    user_prompt = f"{context_line}Transcript segment:\n{text}\n\nReturn JSON only."

    if provider == "anthropic":
        # Use Anthropic Claude API
        headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        body = {
            "model": model,
            "max_tokens": 1024,
            "messages": [
                {"role": "user", "content": f"{system_prompt}\n\n{user_prompt}"}
            ],
        }
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=body,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["content"][0]["text"]

    elif provider == "openai":
        base = api_base or "https://api.openai.com/v1"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        resp = requests.post(f"{base}/chat/completions", headers=headers, json=body, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]

    else:
        raise ValueError(f"Unsupported provider: {provider}. Use 'anthropic' or 'openai'.")

    # Extract JSON from response
    match = re.search(r"\{[\s\S]*\}", content)
    if not match:
        return {"statistics": [], "quotes": [], "processes": [], "comparisons": []}

    try:
        parsed = json.loads(match.group(0))
        return {
            "numbers": parsed.get("numbers", []) if isinstance(parsed.get("numbers"), list) else [],
            "dates": parsed.get("dates", []) if isinstance(parsed.get("dates"), list) else [],
            "quotes": parsed.get("quotes", []) if isinstance(parsed.get("quotes"), list) else [],
            "processes": parsed.get("processes", []) if isinstance(parsed.get("processes"), list) else [],
            "comparisons": parsed.get("comparisons", []) if isinstance(parsed.get("comparisons"), list) else [],
        }
    except json.JSONDecodeError:
        return {"numbers": [], "dates": [], "quotes": [], "processes": [], "comparisons": []}


def batch_cues(cues: List[SrtCue], batch_size: int = 5) -> List[List[SrtCue]]:
    """Group cues into batches for more efficient LLM calls."""
    batches = []
    for i in range(0, len(cues), batch_size):
        batches.append(cues[i:i + batch_size])
    return batches


# ---------------------------------------------------------------------------
# Process/Concept Continuation Detection
# ---------------------------------------------------------------------------

# Discourse markers that signal a process or list is beginning
PROCESS_START_PATTERNS = [
    r"\b(here'?s how|let me (show|explain|walk)|i'?ll (show|explain|walk))\b",
    r"\b(there are|here are)\s+(\d+|several|a few|some)\s+(steps?|things?|ways?|points?|reasons?)\b",
    r"\b(step (one|1)|first(ly)?|to (start|begin))\b",
    r"\b(the (first|1st) (step|thing|point))\b",
    r"\b(number one|#1)\b",
    r"\b(consider (this|the following)|think about)\b",
]

# Markers that indicate continuation of a sequence
PROCESS_CONTINUATION_PATTERNS = [
    r"\b(second(ly)?|step (two|2)|next|then|after that)\b",
    r"\b(third(ly)?|step (three|3)|another)\b",
    r"\b(fourth(ly)?|step (four|4)|also)\b",
    r"\b(fifth(ly)?|step (five|5))\b",
    r"\b(number (two|three|four|five|\d+)|#[2-9])\b",
    r"\b(additionally|furthermore|moreover)\b",
    r"\b(and (then|next|finally))\b",
]

# Markers that signal the end of a process or list
PROCESS_END_PATTERNS = [
    r"\b(finally|lastly|last(ly)?|in conclusion)\b",
    r"\b(to (summarize|sum up|recap|conclude))\b",
    r"\b(that'?s (it|all|how)|and that'?s)\b",
    r"\b(the (last|final) (step|thing|point))\b",
    r"\b(so (there you have it|that'?s how))\b",
]

# Topic shift indicators (potential concept boundary)
TOPIC_SHIFT_PATTERNS = [
    r"\b(now let'?s|moving on|but (first|now)|however)\b",
    r"\b(on (another|a different) note)\b",
    r"\b(switching gears|changing topics?)\b",
    r"\b(anyway|anyhow|at any rate)\b",
]


def _compile_patterns(patterns: List[str]) -> re.Pattern:
    """Compile a list of patterns into a single regex."""
    combined = "|".join(f"({p})" for p in patterns)
    return re.compile(combined, re.IGNORECASE)


PROCESS_START_RE = _compile_patterns(PROCESS_START_PATTERNS)
PROCESS_CONT_RE = _compile_patterns(PROCESS_CONTINUATION_PATTERNS)
PROCESS_END_RE = _compile_patterns(PROCESS_END_PATTERNS)
TOPIC_SHIFT_RE = _compile_patterns(TOPIC_SHIFT_PATTERNS)


@dataclass
class ProcessMarker:
    """Tracks detected process/list structure in transcript."""
    cue_idx: int
    marker_type: str  # 'start', 'continuation', 'end', 'topic_shift'
    text: str


def detect_process_markers(cues: List[SrtCue]) -> List[ProcessMarker]:
    """Scan cues for discourse markers indicating processes or lists."""
    markers = []
    for cue in cues:
        text = cue.text
        if PROCESS_START_RE.search(text):
            markers.append(ProcessMarker(cue.index, 'start', text))
        elif PROCESS_END_RE.search(text):
            markers.append(ProcessMarker(cue.index, 'end', text))
        elif PROCESS_CONT_RE.search(text):
            markers.append(ProcessMarker(cue.index, 'continuation', text))
        elif TOPIC_SHIFT_RE.search(text):
            markers.append(ProcessMarker(cue.index, 'topic_shift', text))
    return markers


def sliding_window_batches(
    cues: List[SrtCue],
    window_size: int = 8,
    step: int = 5,
    markers: Optional[List[ProcessMarker]] = None,
) -> List[List[SrtCue]]:
    """
    Create overlapping sliding window batches for better concept continuity.

    When a process marker is detected, extends the window to include context
    until an end marker or topic shift is found.

    Args:
        cues: List of SRT cues
        window_size: Base window size (default 8 cues)
        step: Step size between windows (default 5, giving 3-cue overlap)
        markers: Optional pre-computed process markers

    Returns:
        List of cue batches with overlapping windows
    """
    if not cues:
        return []

    # Build marker index for quick lookup
    marker_by_idx = {}
    if markers:
        for m in markers:
            marker_by_idx[m.cue_idx] = m

    batches = []
    i = 0

    while i < len(cues):
        # Start with base window
        end_idx = min(i + window_size, len(cues))
        batch_cues = cues[i:end_idx]

        # Check if we're in the middle of a process
        # Look for start markers in current batch without matching end
        has_open_process = False
        for cue in batch_cues:
            marker = marker_by_idx.get(cue.index)
            if marker:
                if marker.marker_type == 'start':
                    has_open_process = True
                elif marker.marker_type in ('end', 'topic_shift'):
                    has_open_process = False

        # If process is open, extend window until we find end/shift or hit limit
        if has_open_process:
            extension_limit = 6  # Max extra cues to add
            extended = 0
            while end_idx < len(cues) and extended < extension_limit:
                next_cue = cues[end_idx]
                marker = marker_by_idx.get(next_cue.index)
                batch_cues.append(next_cue)
                end_idx += 1
                extended += 1
                if marker and marker.marker_type in ('end', 'topic_shift'):
                    break

        batches.append(batch_cues)
        i += step

    return batches


def deduplicate_elements(
    elements: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Remove duplicate elements that may appear from overlapping windows.

    Uses a combination of element_type, cue_idx, and content similarity.
    """
    seen = {}  # (element_type, cue_idx, content_hash) -> element_id
    deduplicated = {}

    for elem_id, elem in elements.items():
        elem_type = elem.get('element_type', '')
        cue_idx = elem.get('cue_idx', 0)

        # Create content hash based on element type
        if elem_type == 'process':
            # For processes, use title and step count
            content_key = (elem.get('title', ''), len(elem.get('steps', [])))
        elif elem_type == 'quote':
            content_key = elem.get('text', '')[:50]
        elif elem_type == 'number':
            content_key = (elem.get('value', ''), tuple(elem.get('raw_numbers', [])))
        elif elem_type == 'date':
            content_key = (elem.get('date', ''), elem.get('event', ''))
        elif elem_type == 'comparison':
            content_key = (elem.get('before', ''), elem.get('after', ''))
        else:
            content_key = str(elem)[:100]

        key = (elem_type, cue_idx, content_key)

        if key not in seen:
            seen[key] = elem_id
            deduplicated[elem_id] = elem
        # If duplicate, keep the one with more complete data (e.g., more steps)
        elif elem_type == 'process':
            existing_id = seen[key]
            existing = deduplicated[existing_id]
            if len(elem.get('steps', [])) > len(existing.get('steps', [])):
                del deduplicated[existing_id]
                deduplicated[elem_id] = elem
                seen[key] = elem_id

    return deduplicated


def call_llm_extract_visuals_batch(
    provider: str,
    model: str,
    cues: List[SrtCue],
    context: Optional[str],
    api_key: Optional[str],
    api_base: Optional[str],
) -> Dict[int, Dict[str, Any]]:
    """
    Extract visual opportunities from multiple cues in a single LLM call.

    Returns dict mapping cue_idx -> extraction results.
    """
    system_prompt = """You extract visual opportunities from transcript segments for motion graphics.

CRITICAL: Look ACROSS cues for related information and multi-cue concepts!

Return JSON with cue indices as keys:
{
  "1": {
    "numbers": [...],
    "dates": [...],
    "quotes": [...],
    "processes": [...],
    "comparisons": [...]
  },
  "2": {...}
}

Element schemas:
- numbers: {"value": "85 of 90", "label": "Refused", "number_type": "ratio|count|percentage|measurement|duration|money", "visualization": "pie_chart|counter|bar|icon_array|none", "raw_numbers": [85, 90], "unit": "string or null"}
- dates: {"date": "18 April 1857", "event": "Execution", "date_type": "specific|period|duration", "is_timeline_worthy": true}
- quotes: {"text": "quote", "speaker": "Name", "quote_type": "historical|defiant|ironic|emotional|explanatory", "is_quotable": true}
- processes: {"title": "name", "steps": ["step1", "step2"], "is_complete": true, "visualization": "flowchart|bullet_list|numbered_list|flywheel|timeline|none"}
- comparisons: {"before": "old", "after": "new", "dimension": "what changed", "visualization": "side_by_side|arrow|scale"}

GUIDELINES:

NUMBERS: Combine related numbers across cues!
- "90 ordered" + "85 refused" → ONE entry: {"value": "85 of 90", "raw_numbers": [85, 90]}
- Durations go here with number_type: "duration"

PROCESSES: This is critical - look for multi-cue explanations!
- Signal phrases: "here's how", "there are X steps", "first... second... third", "the key to", "you need to"
- ALWAYS collect ALL steps even if they span multiple cues
- Set is_complete: false if the process seems cut off or you don't see a conclusion
- Choose visualization based on content:
  - "flowchart": sequential cause-and-effect or decision trees
  - "bullet_list": unordered tips, features, or concepts
  - "numbered_list": ordered steps or priorities
  - "flywheel": cyclical/reinforcing processes (compound interest, virtuous cycles)
  - "timeline": chronological events or phases
- Examples of processes across cues:
  - Cue 10: "There are three ways to build wealth"
  - Cue 11: "First, reduce your expenses"
  - Cue 12: "Second, increase your income"
  - Cue 13: "Third, invest the difference"
  → Process on cue 13 with all 3 steps, visualization: "numbered_list"

COMPARISONS: Before/after, old vs new, A vs B relationships

QUOTES: Be very selective - only truly memorable or significant statements

Use empty arrays [] when nothing found. Return valid JSON only."""

    # Format cues for batch processing
    cue_texts = []
    for cue in cues:
        cue_texts.append(f"[Cue {cue.index}] {cue.text}")

    context_line = f"Video context: {context}\n\n" if context else ""
    user_prompt = f"{context_line}Transcript segments:\n\n" + "\n\n".join(cue_texts) + "\n\nReturn JSON only."

    if provider == "anthropic":
        headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        body = {
            "model": model,
            "max_tokens": 4096,
            "messages": [
                {"role": "user", "content": f"{system_prompt}\n\n{user_prompt}"}
            ],
        }
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=body,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["content"][0]["text"]

    elif provider == "openai":
        base = api_base or "https://api.openai.com/v1"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        resp = requests.post(f"{base}/chat/completions", headers=headers, json=body, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]

    else:
        raise ValueError(f"Unsupported provider: {provider}")

    # Parse response
    match = re.search(r"\{[\s\S]*\}", content)
    if not match:
        return {}

    try:
        parsed = json.loads(match.group(0))
        # Convert string keys to int for cue indices
        results = {}
        for key, value in parsed.items():
            try:
                cue_idx = int(key)
                results[cue_idx] = {
                    "numbers": value.get("numbers", []) if isinstance(value.get("numbers"), list) else [],
                    "dates": value.get("dates", []) if isinstance(value.get("dates"), list) else [],
                    "quotes": value.get("quotes", []) if isinstance(value.get("quotes"), list) else [],
                    "processes": value.get("processes", []) if isinstance(value.get("processes"), list) else [],
                    "comparisons": value.get("comparisons", []) if isinstance(value.get("comparisons"), list) else [],
                }
            except (ValueError, TypeError):
                continue
        return results
    except json.JSONDecodeError:
        return {}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract visual elements (stats, quotes, processes, comparisons) from SRT"
    )
    parser.add_argument("--srt", required=True, help="Path to SRT transcript")
    parser.add_argument("--out", required=True, help="Output JSON path")
    parser.add_argument(
        "--provider",
        choices=["anthropic", "openai"],
        default="anthropic",
        help="LLM provider (default: anthropic)",
    )
    parser.add_argument(
        "--model",
        help="Model name (default: claude-3-5-haiku-20241022 for anthropic, gpt-4o-mini for openai)",
    )
    parser.add_argument("--delay", type=float, default=0.2, help="Delay between LLM calls (seconds)")
    parser.add_argument("--fps", type=float, default=25.0, help="FPS for timecode conversion")
    parser.add_argument("--context", type=str, help="Video topic/context for better extraction")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="Window size for sliding window batching (default: 8)",
    )
    parser.add_argument(
        "--step-size",
        type=int,
        default=5,
        help="Step size between windows, controls overlap (default: 5, giving 3-cue overlap)",
    )
    parser.add_argument(
        "--no-batch",
        action="store_true",
        help="Process cues one at a time (slower but more reliable)",
    )
    parser.add_argument(
        "--no-sliding",
        action="store_true",
        help="Use fixed batches instead of sliding windows (faster, may miss cross-boundary concepts)",
    )
    parser.add_argument(
        "--detect-processes",
        action="store_true",
        default=True,
        help="Use discourse markers to extend context for detected processes (default: True)",
    )
    parser.add_argument(
        "--no-detect-processes",
        action="store_false",
        dest="detect_processes",
        help="Disable process marker detection",
    )
    args = parser.parse_args(argv)

    # Set default model based on provider
    if not args.model:
        args.model = "claude-3-5-haiku-20241022" if args.provider == "anthropic" else "gpt-4o-mini"

    # Load API key
    if args.provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("Error: ANTHROPIC_API_KEY not set", file=sys.stderr)
            return 1
        api_base = None
    else:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("Error: OPENAI_API_KEY not set", file=sys.stderr)
            return 1
        api_base = os.environ.get("OPENAI_API_BASE")

    # Parse SRT
    cues = parse_srt(args.srt, fps=args.fps)
    if not cues:
        print("No cues parsed from SRT.", file=sys.stderr)
        return 2

    print(f"Parsed {len(cues)} cues from {args.srt}")

    # Track all extracted elements
    visual_elements: Dict[str, Dict[str, Any]] = {}
    counters = {"number": 0, "date": 0, "quote": 0, "process": 0, "comparison": 0}

    def process_result(result: Dict[str, Any], cue: SrtCue) -> Dict[str, int]:
        """Process extraction result and add to visual_elements. Returns counts."""
        counts = {"numbers": 0, "dates": 0, "quotes": 0, "processes": 0, "comparisons": 0}

        # Process numbers (formerly statistics)
        for num in result.get("numbers", []):
            counters["number"] += 1
            counts["numbers"] += 1
            elem_id = f"number_{counters['number']:03d}"
            visual_elements[elem_id] = {
                "element_type": "number",
                "value": num.get("value", ""),
                "label": num.get("label", ""),
                "number_type": num.get("number_type", "count"),
                "visualization": num.get("visualization", "counter"),
                "raw_numbers": num.get("raw_numbers", []),
                "unit": num.get("unit"),
                "timecode": cue.start,
                "cue_idx": cue.index,
                "source_text": cue.text,
            }

        # Process dates
        for date in result.get("dates", []):
            counters["date"] += 1
            counts["dates"] += 1
            elem_id = f"date_{counters['date']:03d}"
            visual_elements[elem_id] = {
                "element_type": "date",
                "date": date.get("date", ""),
                "event": date.get("event", ""),
                "date_type": date.get("date_type", "specific"),
                "is_timeline_worthy": date.get("is_timeline_worthy", False),
                "timecode": cue.start,
                "cue_idx": cue.index,
                "source_text": cue.text,
            }

        # Process quotes
        for quote in result.get("quotes", []):
            # Skip non-quotable quotes
            if not quote.get("is_quotable", True):
                continue
            counters["quote"] += 1
            counts["quotes"] += 1
            elem_id = f"quote_{counters['quote']:03d}"
            visual_elements[elem_id] = {
                "element_type": "quote",
                "text": quote.get("text", ""),
                "speaker": quote.get("speaker", "Unknown"),
                "quote_type": quote.get("quote_type", "historical"),
                "timecode": cue.start,
                "cue_idx": cue.index,
                "source_text": cue.text,
            }

        # Process processes
        for proc in result.get("processes", []):
            # Skip processes with fewer than 2 steps (likely false positives)
            steps = proc.get("steps", [])
            if len(steps) < 2:
                continue
            counters["process"] += 1
            counts["processes"] += 1
            elem_id = f"process_{counters['process']:03d}"
            visual_elements[elem_id] = {
                "element_type": "process",
                "title": proc.get("title", ""),
                "steps": steps,
                "step_count": len(steps),
                "is_complete": proc.get("is_complete", False),
                "visualization": proc.get("visualization", "numbered_list"),
                "timecode": cue.start,
                "cue_idx": cue.index,
                "source_text": cue.text,
            }

        # Process comparisons
        for comp in result.get("comparisons", []):
            counters["comparison"] += 1
            counts["comparisons"] += 1
            elem_id = f"comparison_{counters['comparison']:03d}"
            visual_elements[elem_id] = {
                "element_type": "comparison",
                "before": comp.get("before", ""),
                "after": comp.get("after", ""),
                "dimension": comp.get("dimension", ""),
                "visualization": comp.get("visualization", "side_by_side"),
                "timecode": cue.start,
                "cue_idx": cue.index,
                "source_text": cue.text,
            }

        return counts

    # Detect process markers if enabled
    markers = None
    if args.detect_processes and not args.no_batch:
        markers = detect_process_markers(cues)
        if markers:
            start_count = sum(1 for m in markers if m.marker_type == 'start')
            cont_count = sum(1 for m in markers if m.marker_type == 'continuation')
            end_count = sum(1 for m in markers if m.marker_type == 'end')
            print(f"Detected process markers: {start_count} starts, {cont_count} continuations, {end_count} ends")

    if args.no_batch:
        # Process cues one at a time
        total = len(cues)
        for idx, cue in enumerate(cues, start=1):
            print(f"[{idx}/{total}] Extracting visuals for {cue.start} --> {cue.end}", flush=True)

            try:
                result = call_llm_extract_visuals(
                    provider=args.provider,
                    model=args.model,
                    text=cue.text,
                    context=args.context,
                    api_key=api_key,
                    api_base=api_base,
                )

                counts = process_result(result, cue)
                print(f"  -> numbers:{counts['numbers']} dates:{counts['dates']} quotes:{counts['quotes']} "
                      f"processes:{counts['processes']} comparisons:{counts['comparisons']}")

            except Exception as e:
                print(f"  -> Error: {e}", file=sys.stderr)

            time.sleep(max(0.0, args.delay))
    else:
        # Batch processing with sliding windows or fixed batches
        if args.no_sliding:
            batches = batch_cues(cues, args.batch_size)
            print(f"Processing in {len(batches)} fixed batches of up to {args.batch_size} cues each")
        else:
            batches = sliding_window_batches(
                cues,
                window_size=args.batch_size,
                step=args.step_size,
                markers=markers,
            )
            overlap = args.batch_size - args.step_size
            print(f"Processing with sliding windows: size={args.batch_size}, step={args.step_size} ({overlap}-cue overlap)")
            print(f"Total windows: {len(batches)} (may extend for detected processes)")

        total_batches = len(batches)

        for batch_idx, batch in enumerate(batches, start=1):
            first_tc = batch[0].start
            last_tc = batch[-1].end
            print(f"[Batch {batch_idx}/{total_batches}] {first_tc} --> {last_tc} ({len(batch)} cues)", flush=True)

            try:
                results = call_llm_extract_visuals_batch(
                    provider=args.provider,
                    model=args.model,
                    cues=batch,
                    context=args.context,
                    api_key=api_key,
                    api_base=api_base,
                )

                batch_counts = {"numbers": 0, "dates": 0, "quotes": 0, "processes": 0, "comparisons": 0}

                for cue in batch:
                    result = results.get(cue.index, {})
                    counts = process_result(result, cue)
                    for k, v in counts.items():
                        batch_counts[k] += v

                print(f"  -> numbers:{batch_counts['numbers']} dates:{batch_counts['dates']} "
                      f"quotes:{batch_counts['quotes']} processes:{batch_counts['processes']} "
                      f"comparisons:{batch_counts['comparisons']}")

            except Exception as e:
                print(f"  -> Batch error: {e}", file=sys.stderr)
                # Fall back to single-cue processing for this batch
                print("  -> Falling back to single-cue processing...")
                for cue in batch:
                    try:
                        result = call_llm_extract_visuals(
                            provider=args.provider,
                            model=args.model,
                            text=cue.text,
                            context=args.context,
                            api_key=api_key,
                            api_base=api_base,
                        )
                        process_result(result, cue)
                    except Exception as e2:
                        print(f"    -> Cue {cue.index} error: {e2}", file=sys.stderr)
                    time.sleep(max(0.0, args.delay))

            time.sleep(max(0.0, args.delay))

    # Deduplicate elements from overlapping windows
    if not args.no_sliding and not args.no_batch:
        original_count = len(visual_elements)
        visual_elements = deduplicate_elements(visual_elements)
        dedup_count = original_count - len(visual_elements)
        if dedup_count > 0:
            print(f"\nDeduplicated {dedup_count} overlapping elements")

        # Recount after deduplication
        counters = {"number": 0, "date": 0, "quote": 0, "process": 0, "comparison": 0}
        for elem in visual_elements.values():
            elem_type = elem.get("element_type", "")
            if elem_type in counters:
                counters[elem_type] += 1

    # Write output
    output = {
        "visual_elements": visual_elements,
        "source_srt": os.path.abspath(args.srt),
        "summary": {
            "total_elements": len(visual_elements),
            "numbers": counters["number"],
            "dates": counters["date"],
            "quotes": counters["quote"],
            "processes": counters["process"],
            "comparisons": counters["comparison"],
        },
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nWrote {args.out} with {len(visual_elements)} visual elements:")
    print(f"  - Numbers:     {counters['number']}")
    print(f"  - Dates:       {counters['date']}")
    print(f"  - Quotes:      {counters['quote']}")
    print(f"  - Processes:   {counters['process']}")
    print(f"  - Comparisons: {counters['comparison']}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
