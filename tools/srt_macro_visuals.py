#!/usr/bin/env python3
"""
srt_macro_visuals.py

Two-pass visual element extraction for complex, progressively-revealed concepts.

Pass 1: Identify "macro" visual elements from full transcript (matrices, frameworks,
        multi-step processes that span the entire video)
Pass 2: Track how each macro element is built up across the video

This complements srt_visual_elements.py which handles cue-level extraction.

Usage:
  python tools/srt_macro_visuals.py --srt path/to/timeline.srt --out macro_visuals.json

Env:
  - ANTHROPIC_API_KEY or OPENAI_API_KEY
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Auto-load API keys from config file
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: F401

import requests


def parse_srt_to_text(path: str) -> tuple[str, List[dict]]:
    """Parse SRT file and return full text plus cue metadata."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    blocks = re.split(r"\n\s*\n", content.strip(), flags=re.MULTILINE)
    cues = []
    full_text_parts = []

    for block in blocks:
        lines = [ln.strip("\ufeff").strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue

        # Try to parse as SRT
        if re.match(r"^\d+$", lines[0]):
            # Standard SRT with index
            time_match = re.match(r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})", lines[1])
            if time_match:
                text = " ".join(lines[2:])
                cues.append({
                    "index": int(lines[0]),
                    "start": time_match.group(1).replace(".", ","),
                    "end": time_match.group(2).replace(".", ","),
                    "text": text,
                })
                full_text_parts.append(text)

    full_text = " ".join(full_text_parts)
    return full_text, cues


def call_pass1_identify_macros(
    provider: str,
    model: str,
    full_text: str,
    api_key: str,
    api_base: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Pass 1: Identify macro visual elements from the full transcript.

    Returns a list of macro elements like matrices, frameworks, multi-part processes.
    """
    system_prompt = """You analyze video transcripts to identify MACRO visual elements -
complex visualizations that are revealed progressively throughout the video.

Look for:
1. MATRICES/GRIDS: 2x2 matrices, quadrant models, grids with axes
2. FRAMEWORKS: Named frameworks with multiple components (e.g., "The 5 Love Languages")
3. MULTI-PART PROCESSES: Processes with 4+ steps revealed across the video
4. DIAGRAMS: Pyramids, funnels, cycles, spectrums mentioned by name
5. COMPARISONS: Extended before/after or type-A vs type-B comparisons

For each macro element found, return:
{
  "macro_id": "unique_snake_case_id",
  "macro_type": "matrix|framework|process|diagram|comparison",
  "name": "The name used in the video (e.g., 'Self-Abandonment Matrix')",
  "structure": {
    // For matrices:
    "x_axis": "what the x-axis measures",
    "y_axis": "what the y-axis measures",
    "quadrants": ["name1", "name2", "name3", "name4"]
    // For frameworks:
    "components": ["component1", "component2", ...]
    // For processes:
    "steps": ["step1", "step2", ...]
    // For diagrams:
    "elements": ["element1", "element2", ...]
  },
  "visualization_suggestion": "2x2_grid|pyramid|flowchart|spectrum|etc",
  "key_quotes": ["verbatim quotes that define this element"]
}

Return JSON array of macro elements. If none found, return [].
Be thorough - these are the KEY visual moments in the video."""

    user_prompt = f"""Analyze this transcript and identify all macro visual elements:

{full_text[:30000]}

Return JSON array only."""

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
        content = resp.json()["content"][0]["text"]

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
        content = resp.json()["choices"][0]["message"]["content"]

    else:
        raise ValueError(f"Unsupported provider: {provider}")

    # Parse JSON from response
    match = re.search(r"\[[\s\S]*\]", content)
    if not match:
        return []

    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return []


def match_quote_to_cue(quote: str, cues: List[dict]) -> Optional[dict]:
    """Find the cue that best matches a quote, returning cue with timecode."""
    if not quote or not cues:
        return None

    # Normalize quote for matching
    quote_lower = quote.lower().strip()
    quote_words = set(re.findall(r'\w+', quote_lower))

    best_match = None
    best_score = 0

    for cue in cues:
        cue_text = cue.get("text", "").lower()
        cue_words = set(re.findall(r'\w+', cue_text))

        # Calculate word overlap score
        if not cue_words:
            continue

        overlap = len(quote_words & cue_words)
        score = overlap / max(len(quote_words), 1)

        # Also check for substring match
        if quote_lower[:30] in cue_text or cue_text in quote_lower:
            score += 0.5

        if score > best_score:
            best_score = score
            best_match = cue

    # Only return if we have a reasonable match
    if best_score >= 0.3 and best_match:
        return best_match
    return None


def call_pass2_track_reveals(
    provider: str,
    model: str,
    full_text: str,
    macros: List[Dict[str, Any]],
    cues: List[dict],
    api_key: str,
    api_base: Optional[str] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Pass 2: Track when and how each macro element is revealed across the video.

    Returns a dict mapping macro_id to list of reveal moments with timecodes.
    """
    if not macros:
        return {}

    macro_names = [m.get("name", m.get("macro_id", "unknown")) for m in macros]

    system_prompt = f"""You track when visual elements are revealed in a video transcript.

The video contains these macro visual elements:
{json.dumps(macros, indent=2)}

For each reference to these elements in the transcript, identify:
1. Which macro element is being referenced
2. What NEW information is being added (new quadrant, new axis label, new step, etc.)
3. A SHORT, EXACT quote from the transcript (15-30 words) that we can match to find the timecode

Return JSON:
{{
  "macro_id_1": [
    {{
      "reveal_type": "introduction|axis_definition|quadrant_reveal|step_addition|summary",
      "new_info": "what new information is revealed",
      "quote": "SHORT exact quote from transcript (15-30 words, must be verbatim)"
    }}
  ],
  "macro_id_2": [...]
}}

IMPORTANT: Quotes must be EXACT and SHORT so we can match them to get timecodes.
Track EVERY mention that adds information to the visual element."""

    user_prompt = f"""Track reveals of the macro elements in this transcript:

{full_text[:30000]}

Return JSON only."""

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
        content = resp.json()["content"][0]["text"]

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
        content = resp.json()["choices"][0]["message"]["content"]

    else:
        raise ValueError(f"Unsupported provider: {provider}")

    # Parse JSON from response
    match = re.search(r"\{[\s\S]*\}", content)
    if not match:
        return {}

    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract macro visual elements (matrices, frameworks) from SRT"
    )
    parser.add_argument("--srt", required=True, help="Path to SRT transcript")
    parser.add_argument(
        "--out",
        help="Output JSON path (default: same directory as SRT with _macro.json suffix)",
    )
    parser.add_argument(
        "--provider",
        choices=["anthropic", "openai"],
        default="openai",
        help="LLM provider (default: openai)",
    )
    parser.add_argument(
        "--model",
        help="Model name (default: gpt-4o for openai, claude-3-5-sonnet-20241022 for anthropic)",
    )
    args = parser.parse_args(argv)

    # Default output to same directory as source SRT
    if not args.out:
        srt_path = Path(args.srt)
        args.out = str(srt_path.parent / f"{srt_path.stem}_macro.json")

    # Set default model - use more capable models for this task
    if not args.model:
        args.model = "gpt-4o" if args.provider == "openai" else "claude-3-5-sonnet-20241022"

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
    print(f"Parsing {args.srt}...")
    full_text, cues = parse_srt_to_text(args.srt)
    print(f"  {len(cues)} cues, {len(full_text)} characters")

    # Pass 1: Identify macro elements
    print(f"\nPass 1: Identifying macro visual elements using {args.model}...")
    macros = call_pass1_identify_macros(
        provider=args.provider,
        model=args.model,
        full_text=full_text,
        api_key=api_key,
        api_base=api_base,
    )

    if not macros:
        print("  No macro elements found.")
        output = {"macro_elements": [], "reveals": {}, "source_srt": os.path.abspath(args.srt)}
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\nWrote {args.out} (no macro elements)")
        return 0

    print(f"  Found {len(macros)} macro element(s):")
    for m in macros:
        print(f"    - {m.get('name', 'unnamed')} ({m.get('macro_type', 'unknown')})")

    # Pass 2: Track reveals
    print(f"\nPass 2: Tracking progressive reveals...")
    raw_reveals = call_pass2_track_reveals(
        provider=args.provider,
        model=args.model,
        full_text=full_text,
        macros=macros,
        cues=cues,
        api_key=api_key,
        api_base=api_base,
    )

    # Match quotes to cues to get timecodes
    reveals = {}
    matched_count = 0
    for macro_id, reveal_list in raw_reveals.items():
        reveals[macro_id] = []
        for reveal in reveal_list:
            quote = reveal.get("quote", "")
            matched_cue = match_quote_to_cue(quote, cues)

            enriched_reveal = {
                "reveal_type": reveal.get("reveal_type", "unknown"),
                "new_info": reveal.get("new_info", ""),
                "quote": quote,
            }

            if matched_cue:
                enriched_reveal["timecode"] = matched_cue["start"]
                enriched_reveal["cue_idx"] = matched_cue["index"]
                matched_count += 1
            else:
                enriched_reveal["timecode"] = None
                enriched_reveal["cue_idx"] = None

            reveals[macro_id].append(enriched_reveal)

    total_reveals = sum(len(r) for r in reveals.values())
    print(f"  Tracked {total_reveals} reveal moments ({matched_count} with timecodes)")

    # Write output
    output = {
        "macro_elements": macros,
        "reveals": reveals,
        "source_srt": os.path.abspath(args.srt),
        "summary": {
            "total_macros": len(macros),
            "total_reveals": total_reveals,
        },
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nWrote {args.out}")
    print(f"  Macro elements: {len(macros)}")
    print(f"  Reveal moments: {total_reveals}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
