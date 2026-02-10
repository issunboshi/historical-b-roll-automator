#!/usr/bin/env python3
"""
generate_markers.py

Generate timeline markers from visual_elements.json for import into DaVinci Resolve.
Supports EDL (CMX 3600) and FCP XML formats.

Usage:
  python tools/generate_markers.py visual_elements.json --output markers.edl --format edl --fps 24
  python tools/generate_markers.py visual_elements.json --format xml --timeline-name "B-Roll Markers"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

# Auto-load API keys from config file
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: F401


# Color mappings by element type
# (EDL color name, FCP XML color ID)
COLOR_MAP: Dict[str, Tuple[str, int]] = {
    "date": ("BLUE", 9),
    "quote": ("GREEN", 12),
    "number": ("YELLOW", 6),
    "process": ("RED", 2),
    "comparison": ("PURPLE", 3),
}

DEFAULT_COLOR = ("WHITE", 0)


def parse_visual_elements(json_path: Path) -> List[Dict[str, Any]]:
    """Load and validate visual_elements.json, return sorted list by timecode.

    Args:
        json_path: Path to visual_elements.json

    Returns:
        List of visual element dicts sorted by timecode
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    elements = data.get("visual_elements", {})

    # Convert dict to list and add element_id
    element_list = []
    for element_id, element_data in elements.items():
        element = dict(element_data)
        element["element_id"] = element_id
        element_list.append(element)

    # Sort by timecode
    element_list.sort(key=lambda e: e.get("timecode", "00:00:00,000"))

    return element_list


def srt_timecode_to_frames(timecode: str, fps: float) -> int:
    """Convert SRT timecode '00:00:31,440' to frame number.

    Args:
        timecode: SRT format timecode (HH:MM:SS,mmm)
        fps: Frames per second

    Returns:
        Frame number (0-indexed)
    """
    # Handle both comma and period as millisecond separator
    match = re.match(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})", timecode)
    if not match:
        return 0

    hours, minutes, seconds, millis = map(int, match.groups())
    total_seconds = hours * 3600 + minutes * 60 + seconds + millis / 1000.0
    return int(total_seconds * fps)


def frames_to_edl_timecode(frames: int, fps: float) -> str:
    """Convert frame number to EDL timecode '00:00:31:10'.

    Args:
        frames: Frame number (0-indexed)
        fps: Frames per second

    Returns:
        EDL format timecode (HH:MM:SS:FF)
    """
    total_seconds = frames / fps
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    frame_remainder = int((total_seconds - int(total_seconds)) * fps)

    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frame_remainder:02d}"


def get_marker_label(element: Dict[str, Any]) -> str:
    """Build 'TYPE: key_info' string from element data.

    Args:
        element: Visual element dict

    Returns:
        Formatted marker label
    """
    element_type = element.get("element_type", "unknown").upper()

    if element_type == "DATE":
        date = element.get("date", "")
        event = element.get("event", "")
        if event:
            return f"DATE: {date} - {event}"
        return f"DATE: {date}"

    elif element_type == "QUOTE":
        text = element.get("text", "")
        # Truncate long quotes
        if len(text) > 50:
            text = text[:47] + "..."
        return f'QUOTE: "{text}"'

    elif element_type == "NUMBER":
        value = element.get("value", "")
        label = element.get("label", "")
        if label:
            return f"NUMBER: {value} {label}"
        return f"NUMBER: {value}"

    elif element_type == "PROCESS":
        title = element.get("title", "")
        step_count = element.get("step_count", len(element.get("steps", [])))
        return f"PROCESS: {title} ({step_count} steps)"

    elif element_type == "COMPARISON":
        before = element.get("before", element.get("item1", ""))
        after = element.get("after", element.get("item2", ""))
        return f"COMPARISON: {before} vs {after}"

    else:
        # Fallback for unknown types
        return f"{element_type}: {element.get('element_id', 'unknown')}"


def get_marker_color(element_type: str) -> Tuple[str, int]:
    """Return (edl_color_name, xml_color_id) for element type.

    Args:
        element_type: Type of visual element (date, quote, number, etc.)

    Returns:
        Tuple of (EDL color name, FCP XML color ID)
    """
    return COLOR_MAP.get(element_type.lower(), DEFAULT_COLOR)


def generate_edl(elements: List[Dict[str, Any]], fps: float, title: str) -> str:
    """Generate CMX 3600 EDL string with marker comments.

    Args:
        elements: List of visual element dicts
        fps: Frames per second
        title: Timeline/sequence name

    Returns:
        EDL content as string
    """
    lines = [
        f"TITLE: {title}",
        "FCM: NON-DROP FRAME",
        "",
    ]

    for idx, element in enumerate(elements, start=1):
        timecode = element.get("timecode", "00:00:00,000")
        frames = srt_timecode_to_frames(timecode, fps)
        edl_tc = frames_to_edl_timecode(frames, fps)
        edl_tc_end = frames_to_edl_timecode(frames + 1, fps)

        element_type = element.get("element_type", "unknown")
        color_name, _ = get_marker_color(element_type)
        label = get_marker_label(element)
        source_text = element.get("source_text", "")

        # EDL event line (1-frame duration, auxiliary mark)
        lines.append(f"{idx:03d}  AX       V     C        {edl_tc} {edl_tc_end} {edl_tc} {edl_tc_end}")
        # Marker/locator comment with color
        lines.append(f"* LOC: {edl_tc} {color_name}     {label}")
        # Source text as additional comment
        if source_text:
            # Escape any special characters and truncate if too long
            clean_source = source_text.replace("\n", " ").replace("\r", " ")
            lines.append(f"* SOURCE: {clean_source}")
        lines.append("")

    return "\n".join(lines)


def generate_xml(elements: List[Dict[str, Any]], fps: float, title: str) -> str:
    """Generate FCP 7 XML with markers.

    Args:
        elements: List of visual element dicts
        fps: Frames per second
        title: Timeline/sequence name

    Returns:
        XML content as string
    """
    # Build XML structure
    xmeml = ET.Element("xmeml", version="5")
    sequence = ET.SubElement(xmeml, "sequence")

    name = ET.SubElement(sequence, "name")
    name.text = title

    rate = ET.SubElement(sequence, "rate")
    timebase = ET.SubElement(rate, "timebase")
    timebase.text = str(int(fps))

    media = ET.SubElement(sequence, "media")
    video = ET.SubElement(media, "video")
    track = ET.SubElement(video, "track")

    # Add markers to track
    for element in elements:
        timecode = element.get("timecode", "00:00:00,000")
        frames = srt_timecode_to_frames(timecode, fps)

        element_type = element.get("element_type", "unknown")
        _, color_id = get_marker_color(element_type)
        label = get_marker_label(element)
        source_text = element.get("source_text", "")

        marker = ET.SubElement(track, "marker")

        marker_name = ET.SubElement(marker, "name")
        marker_name.text = label

        comment = ET.SubElement(marker, "comment")
        comment.text = source_text

        in_point = ET.SubElement(marker, "in")
        in_point.text = str(frames)

        out_point = ET.SubElement(marker, "out")
        out_point.text = str(frames + 1)

        color = ET.SubElement(marker, "color")
        color.text = str(color_id)

    # Convert to string with XML declaration
    ET.indent(xmeml, space="  ")
    xml_str = ET.tostring(xmeml, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_str}\n'


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point.

    Args:
        argv: Command line arguments (defaults to sys.argv[1:])

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    parser = argparse.ArgumentParser(
        description="Generate timeline markers from visual_elements.json for DaVinci Resolve",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "input",
        help="Path to visual_elements.json"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path (default: <input_dir>/visual_markers.<format>)"
    )
    parser.add_argument(
        "--format", "-f",
        choices=["edl", "xml"],
        default="edl",
        help="Output format"
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=24.0,
        help="Timeline frame rate"
    )
    parser.add_argument(
        "--timeline-name",
        default="Visual Elements",
        help="Timeline/sequence name"
    )

    args = parser.parse_args(argv)

    # Validate input file
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        return 1

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.parent / f"visual_markers.{args.format}"

    # Parse visual elements
    try:
        elements = parse_visual_elements(input_path)
        print(f"Loaded {len(elements)} visual elements from {input_path}")
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Error parsing visual elements: {e}", file=sys.stderr)
        return 1

    if not elements:
        print("Warning: No visual elements found in input file", file=sys.stderr)
        return 0

    # Generate output
    if args.format == "edl":
        content = generate_edl(elements, args.fps, args.timeline_name)
    else:
        content = generate_xml(elements, args.fps, args.timeline_name)

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Generated {args.format.upper()} markers: {output_path}")

    # Summary by type
    type_counts: Dict[str, int] = {}
    for element in elements:
        etype = element.get("element_type", "unknown")
        type_counts[etype] = type_counts.get(etype, 0) + 1

    print("Marker counts by type:")
    for etype, count in sorted(type_counts.items()):
        color_name, _ = get_marker_color(etype)
        print(f"  {etype}: {count} ({color_name})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
