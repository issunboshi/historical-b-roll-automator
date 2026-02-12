#!/usr/bin/env python3
"""
Generate FCP 7 XML for B-Roll placement in DaVinci Resolve.

This script reads an entities_map.json and generates an XML file that can be
imported into DaVinci Resolve with clips placed at the correct timecodes.

Usage:
    python generate_broll_xml.py entities_map.json [options]
    
    Options:
        --output, -o      Output XML file path (default: broll_timeline.xml)
        --fps             Timeline frame rate (default: 25)
        --duration, -d    Clip duration in seconds (default: 4.0)
        --gap, -g         Minimum gap between clips in seconds (default: 2.0)
        --tracks, -t      Number of video tracks to use (default: 4)
        --allow-non-pd    Include non-public-domain images
        --timeline-name   Name for the timeline (default: B-Roll Timeline)

After running:
    1. Open DaVinci Resolve
    2. File > Import > Timeline... (or Import > XML)
    3. Select the generated .xml file
    4. The timeline will be created with clips at correct positions
    5. You may need to relink media if paths differ
"""

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree as ET
from xml.dom import minidom

# Quality level ordering for filtering
QUALITY_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}


def path_to_file_url(filepath: str) -> str:
    """
    Convert a filesystem path to a proper file:// URL for DaVinci Resolve.

    Uses file:/// format (no localhost) which has better compatibility with
    DaVinci Resolve on macOS. Also handles URL-encoded characters in filenames.
    """
    # Split into directory and filename
    dirname = os.path.dirname(filepath)
    basename = os.path.basename(filepath)

    # URL-encode the path components (quote encodes special chars including %)
    # safe='/' keeps forward slashes unencoded in the directory path
    encoded_dir = quote(dirname, safe='/')
    encoded_name = quote(basename, safe='')

    # Use file:/// (no localhost) for better DaVinci Resolve compatibility
    return f"file://{encoded_dir}/{encoded_name}"


def srt_timecode_to_seconds(tc: str) -> float:
    """Convert SRT timecode (HH:MM:SS,mmm) to seconds."""
    match = re.match(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})', tc)
    if not match:
        return 0.0
    h, m, s, ms = match.groups()
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def seconds_to_frames(seconds: float, fps: float) -> int:
    """Convert seconds to frame count."""
    return int(round(seconds * fps))


def frames_to_timecode(frames: int, fps: float) -> str:
    """Convert frame count to SMPTE timecode (HH:MM:SS:FF)."""
    fps_int = int(fps)
    total_seconds = frames // fps_int
    ff = frames % fps_int
    ss = total_seconds % 60
    mm = (total_seconds // 60) % 60
    hh = total_seconds // 3600
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def generate_id() -> str:
    """Generate a unique ID for XML elements."""
    return str(uuid.uuid4()).replace('-', '')[:16]


def create_fcp_xml(placements: list, fps: float, timeline_name: str, clip_duration_sec: float) -> ET.Element:
    """
    Create FCP 7 XML structure with clips at specified positions.
    
    Args:
        placements: List of dicts with keys: frame, track, path, name, duration_frames
        fps: Timeline frame rate
        timeline_name: Name of the timeline
        clip_duration_sec: Default clip duration in seconds
    """
    fps_int = int(fps)
    # Calculate timeline duration (extend past last clip)
    max_frame = max(p['frame'] + p['duration_frames'] for p in placements) if placements else 0
    timeline_duration = max_frame + seconds_to_frames(10, fps)  # Add 10 sec buffer
    
    # Root element
    xmeml = ET.Element('xmeml', version="5")
    
    # Project
    project = ET.SubElement(xmeml, 'project')
    ET.SubElement(project, 'name').text = timeline_name
    
    # Children (bins and sequences)
    children = ET.SubElement(project, 'children')
    
    # Create B-Roll bin to organize media
    broll_bin = ET.SubElement(children, 'bin')
    ET.SubElement(broll_bin, 'name').text = 'B-Roll'
    bin_children = ET.SubElement(broll_bin, 'children')
    
    # Collect unique files and create master clips in the bin
    # Use path as key to avoid duplicates
    file_registry = {}  # path -> {'masterclip_id': ..., 'file_id': ...}
    for p in placements:
        path = p['path']
        if path not in file_registry:
            masterclip_id = f"masterclip-{generate_id()}"
            file_id = f"file-{generate_id()}"
            file_registry[path] = {'masterclip_id': masterclip_id, 'file_id': file_id}

            # Create clip element in bin
            clip = ET.SubElement(bin_children, 'clip', id=masterclip_id)
            ET.SubElement(clip, 'name').text = os.path.basename(path)
            ET.SubElement(clip, 'duration').text = str(p['duration_frames'])

            # Rate
            clip_rate = ET.SubElement(clip, 'rate')
            ET.SubElement(clip_rate, 'timebase').text = str(fps_int)
            ET.SubElement(clip_rate, 'ntsc').text = 'FALSE'

            # File reference (reuse file_id for same media)
            file_elem = ET.SubElement(clip, 'file', id=file_id)
            ET.SubElement(file_elem, 'name').text = os.path.basename(path)
            ET.SubElement(file_elem, 'pathurl').text = path_to_file_url(path)
            # Still images have duration=1 (single frame)
            ET.SubElement(file_elem, 'duration').text = '1'

            f_rate = ET.SubElement(file_elem, 'rate')
            ET.SubElement(f_rate, 'timebase').text = str(fps_int)
            ET.SubElement(f_rate, 'ntsc').text = 'FALSE'

            # Timecode (required by DaVinci for proper media recognition)
            f_tc = ET.SubElement(file_elem, 'timecode')
            ET.SubElement(f_tc, 'string').text = '00:00:00:00'
            ET.SubElement(f_tc, 'displayformat').text = 'NDF'
            f_tc_rate = ET.SubElement(f_tc, 'rate')
            ET.SubElement(f_tc_rate, 'timebase').text = str(fps_int)
            ET.SubElement(f_tc_rate, 'ntsc').text = 'FALSE'

            # Media info
            f_media = ET.SubElement(file_elem, 'media')
            f_video = ET.SubElement(f_media, 'video')
            ET.SubElement(f_video, 'duration').text = '1'
            f_sample = ET.SubElement(f_video, 'samplecharacteristics')
            ET.SubElement(f_sample, 'width').text = '1920'
            ET.SubElement(f_sample, 'height').text = '1080'
    
    # Sequence (timeline)
    sequence = ET.SubElement(children, 'sequence', id=f"sequence-{generate_id()}")
    ET.SubElement(sequence, 'name').text = timeline_name
    ET.SubElement(sequence, 'duration').text = str(timeline_duration)
    
    # Rate
    rate = ET.SubElement(sequence, 'rate')
    ET.SubElement(rate, 'timebase').text = str(fps_int)
    ET.SubElement(rate, 'ntsc').text = 'FALSE'
    
    # Timecode
    tc = ET.SubElement(sequence, 'timecode')
    tc_rate = ET.SubElement(tc, 'rate')
    ET.SubElement(tc_rate, 'timebase').text = str(fps_int)
    ET.SubElement(tc_rate, 'ntsc').text = 'FALSE'
    ET.SubElement(tc, 'string').text = '00:00:00:00'
    ET.SubElement(tc, 'frame').text = '0'
    ET.SubElement(tc, 'displayformat').text = 'NDF'
    
    # Media
    media = ET.SubElement(sequence, 'media')
    
    # Video section
    video = ET.SubElement(media, 'video')
    
    # Video format
    vformat = ET.SubElement(video, 'format')
    sample_chars = ET.SubElement(vformat, 'samplecharacteristics')
    ET.SubElement(sample_chars, 'width').text = '1920'
    ET.SubElement(sample_chars, 'height').text = '1080'
    ET.SubElement(sample_chars, 'pixelaspectratio').text = 'square'
    sc_rate = ET.SubElement(sample_chars, 'rate')
    ET.SubElement(sc_rate, 'timebase').text = str(fps_int)
    ET.SubElement(sc_rate, 'ntsc').text = 'FALSE'
    
    # Group placements by track
    tracks_dict = {}
    for p in placements:
        track_idx = p['track']
        if track_idx not in tracks_dict:
            tracks_dict[track_idx] = []
        tracks_dict[track_idx].append(p)
    
    # Create video tracks
    max_track = max(tracks_dict.keys()) if tracks_dict else 2
    for track_idx in range(1, max_track + 1):
        track = ET.SubElement(video, 'track')
        
        if track_idx == 1:
            # Track V1 is typically the main video - leave empty or add placeholder
            ET.SubElement(track, 'enabled').text = 'TRUE'
            ET.SubElement(track, 'locked').text = 'FALSE'
            continue
        
        track_placements = tracks_dict.get(track_idx, [])
        track_placements.sort(key=lambda x: x['frame'])
        
        for p in track_placements:
            clipitem = ET.SubElement(track, 'clipitem', id=f"clipitem-{generate_id()}")

            # Reference the masterclip from the bin
            file_info = file_registry.get(p['path'])
            if file_info:
                ET.SubElement(clipitem, 'masterclipid').text = file_info['masterclip_id']

            # Clip name
            clip_name = p.get('name', os.path.basename(p['path']))
            ET.SubElement(clipitem, 'name').text = clip_name

            # Duration (clip duration on timeline)
            ET.SubElement(clipitem, 'duration').text = str(p['duration_frames'])

            # Rate
            ci_rate = ET.SubElement(clipitem, 'rate')
            ET.SubElement(ci_rate, 'timebase').text = str(fps_int)
            ET.SubElement(ci_rate, 'ntsc').text = 'FALSE'

            # Timeline position (in/out points on timeline)
            ET.SubElement(clipitem, 'start').text = str(p['frame'])
            ET.SubElement(clipitem, 'end').text = str(p['frame'] + p['duration_frames'])

            # Source in/out (portion of source clip to use)
            ET.SubElement(clipitem, 'in').text = '0'
            ET.SubElement(clipitem, 'out').text = str(p['duration_frames'])

            # File reference - reuse the same file ID from the bin
            # This allows DaVinci to recognize it as the same media
            file_id = file_info['file_id'] if file_info else f"file-{generate_id()}"
            file_elem = ET.SubElement(clipitem, 'file', id=file_id)
            ET.SubElement(file_elem, 'name').text = os.path.basename(p['path'])
            ET.SubElement(file_elem, 'pathurl').text = path_to_file_url(p['path'])

            # Still images have duration=1 (single frame)
            ET.SubElement(file_elem, 'duration').text = '1'

            # File rate
            f_rate = ET.SubElement(file_elem, 'rate')
            ET.SubElement(f_rate, 'timebase').text = str(fps_int)
            ET.SubElement(f_rate, 'ntsc').text = 'FALSE'

            # Timecode (required by DaVinci for proper media recognition)
            f_tc = ET.SubElement(file_elem, 'timecode')
            ET.SubElement(f_tc, 'string').text = '00:00:00:00'
            ET.SubElement(f_tc, 'displayformat').text = 'NDF'
            f_tc_rate = ET.SubElement(f_tc, 'rate')
            ET.SubElement(f_tc_rate, 'timebase').text = str(fps_int)
            ET.SubElement(f_tc_rate, 'ntsc').text = 'FALSE'

            # Media info
            f_media = ET.SubElement(file_elem, 'media')
            f_video = ET.SubElement(f_media, 'video')
            ET.SubElement(f_video, 'duration').text = '1'
            f_sample = ET.SubElement(f_video, 'samplecharacteristics')
            ET.SubElement(f_sample, 'width').text = '1920'
            ET.SubElement(f_sample, 'height').text = '1080'
        
        ET.SubElement(track, 'enabled').text = 'TRUE'
        ET.SubElement(track, 'locked').text = 'FALSE'
    
    # Audio section (empty but required)
    audio = ET.SubElement(media, 'audio')
    audio_track = ET.SubElement(audio, 'track')
    ET.SubElement(audio_track, 'enabled').text = 'TRUE'
    ET.SubElement(audio_track, 'locked').text = 'FALSE'
    
    return xmeml


def prettify_xml(elem: ET.Element) -> str:
    """Return pretty-printed XML string."""
    rough_string = ET.tostring(elem, encoding='unicode')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ", encoding=None)


def calculate_placement_budgets(
    entities: dict,
    pervasive_entities: list,
    max_placements: int = 3,
    pervasive_max: int = 2,
) -> dict:
    """Calculate how many timeline placements each entity gets.

    Args:
        entities: Dict of entity_name -> payload (with priority, occurrences).
        pervasive_entities: List of entity names considered pervasive (broad/setting).
        max_placements: Maximum placements for high-priority entities.
        pervasive_max: Maximum placements for pervasive entities.

    Returns:
        Dict of entity_name -> max allowed placements (int).
    """
    budgets = {}
    pervasive_set = {e.lower() for e in pervasive_entities}

    for name, payload in entities.items():
        occurrences = payload.get("occurrences", [])
        n = len(occurrences)

        if n <= 1:
            budgets[name] = 1
            continue

        # Pervasive entities (auto-detected or from summary)
        if name.lower() in pervasive_set or n >= 10:
            budgets[name] = min(pervasive_max, n)
            continue

        priority = payload.get("priority", 0.5)
        if priority >= 0.8:
            budgets[name] = min(max_placements, n)
        elif priority >= 0.5:
            budgets[name] = min(max(max_placements - 1, 1), n)
        else:
            budgets[name] = min(1, n)

    return budgets


def select_occurrences(occurrences: list, budget: int) -> list:
    """Select which occurrences to place on the timeline.

    Strategy: always include first (introduction), last if budget >= 2,
    then evenly space remaining picks across the middle.

    Args:
        occurrences: Full list of occurrence dicts (with timecodes).
        budget: How many to select.

    Returns:
        Selected occurrences in chronological order.
    """
    n = len(occurrences)
    if budget >= n:
        return list(occurrences)
    if budget <= 0:
        return []

    selected_indices = set()

    # Always include first occurrence
    selected_indices.add(0)

    # Include last if budget allows
    if budget >= 2:
        selected_indices.add(n - 1)

    # Fill remaining budget with evenly spaced middle occurrences
    remaining = budget - len(selected_indices)
    if remaining > 0 and n > 2:
        middle_indices = list(range(1, n - 1))
        step = len(middle_indices) / (remaining + 1)
        for i in range(remaining):
            pick = int(round(step * (i + 1))) - 1
            pick = max(0, min(pick, len(middle_indices) - 1))
            selected_indices.add(middle_indices[pick])

    return [occurrences[i] for i in sorted(selected_indices)]


def main():
    parser = argparse.ArgumentParser(
        description='Generate FCP XML for B-Roll placement in DaVinci Resolve',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
    python generate_broll_xml.py entities_map.json -o my_broll.xml --fps 24 --duration 3

After generating the XML:
    1. Open DaVinci Resolve
    2. File > Import > Timeline...
    3. Select the generated XML file
    4. Relink media if needed (right-click clips > Relink Selected Clips)
        """
    )
    parser.add_argument('input', help='Path to entities_map.json')
    parser.add_argument('-o', '--output', default='broll_timeline.xml',
                        help='Output XML file path (default: broll_timeline.xml)')
    parser.add_argument('--fps', type=float, default=25.0,
                        help='Timeline frame rate (default: 25)')
    parser.add_argument('-d', '--duration', type=float, default=4.0,
                        help='Clip duration in seconds (default: 4.0)')
    parser.add_argument('-g', '--gap', type=float, default=2.0,
                        help='Minimum gap between clips in seconds (default: 2.0)')
    parser.add_argument('-t', '--tracks', type=int, default=4,
                        help='Number of video tracks to use for B-Roll (default: 4)')
    parser.add_argument('--allow-non-pd', action='store_true',
                        help='Include non-public-domain images')
    parser.add_argument('--min-match-quality', default='high',
                        choices=['high', 'medium', 'low', 'none'],
                        help='Minimum match quality to include (default: high)')
    parser.add_argument('--timeline-name', default='B-Roll Timeline',
                        help='Name for the timeline (default: B-Roll Timeline)')
    parser.add_argument('--montage-clip-duration', type=float, default=0.6,
                        help='Duration per image in montage sequence (default: 0.6s)')
    parser.add_argument('--max-placements', type=int, default=3,
                        help='Max clip placements per entity on timeline (default: 3)')
    parser.add_argument('--pervasive-max', type=int, default=2,
                        help='Max placements for pervasive/background entities (default: 2)')
    parser.add_argument('--summary',
                        help='Path to transcript_summary.json (for pervasive entity list)')

    args = parser.parse_args()
    
    # Read JSON
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: File not found: {args.input}", file=sys.stderr)
        sys.exit(1)
    
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    entities = data.get('entities', {})
    if not entities:
        print("ERROR: No 'entities' found in JSON", file=sys.stderr)
        sys.exit(1)

    # Load transcript summary for pervasive entities list
    pervasive_entities = []
    summary_path = getattr(args, 'summary', None)
    if not summary_path:
        # Auto-detect: look in same directory as input
        candidate = input_path.parent / "transcript_summary.json"
        if candidate.exists():
            summary_path = str(candidate)

    if summary_path and Path(summary_path).exists():
        try:
            with open(summary_path, 'r', encoding='utf-8') as f:
                summary_data = json.load(f)
            pervasive_entities = summary_data.get('pervasive_entities', [])
            if pervasive_entities:
                print(f"Loaded {len(pervasive_entities)} pervasive entities from summary")
        except Exception as e:
            print(f"WARNING: Failed to load summary: {e}", file=sys.stderr)

    # Filter entities by match quality
    excluded_entities = []
    min_quality_level = QUALITY_ORDER.get(args.min_match_quality, 3)

    qualified_entities = {}
    for entity_name, payload in entities.items():
        # Get match quality from disambiguation metadata
        disambiguation = payload.get('disambiguation', {})
        entity_quality = disambiguation.get('match_quality', 'high')  # Default high for pre-Phase4 entities
        entity_quality_level = QUALITY_ORDER.get(entity_quality, 0)

        if entity_quality_level < min_quality_level:
            excluded_entities.append({
                'name': entity_name,
                'quality': entity_quality,
                'reason': f'quality {entity_quality} below threshold {args.min_match_quality}'
            })
            continue
        qualified_entities[entity_name] = payload

    # Calculate placement budgets (frequency capping)
    budgets = calculate_placement_budgets(
        qualified_entities,
        pervasive_entities,
        max_placements=args.max_placements,
        pervasive_max=args.pervasive_max,
    )

    # Build list of clips with timecodes
    clips = []
    montage_count = 0
    montage_clip_frames = seconds_to_frames(args.montage_clip_duration, args.fps)
    capped_entities = 0

    for entity_name, payload in qualified_entities.items():
        images = payload.get('images', [])
        occurrences = payload.get('occurrences', [])

        if not images or not occurrences:
            continue

        # Filter by public domain
        if args.allow_non_pd:
            filtered_images = images
        else:
            filtered_images = [img for img in images if img.get('category') == 'public_domain']

        if not filtered_images:
            continue

        # Apply frequency capping: select which occurrences to use
        budget = budgets.get(entity_name, len(occurrences))
        if budget < len(occurrences):
            selected_occurrences = select_occurrences(occurrences, budget)
            capped_entities += 1
        else:
            selected_occurrences = occurrences

        # Check if this is a montage entity
        is_montage = payload.get('is_montage', False)
        montage_image_count = payload.get('montage_image_count', len(filtered_images))

        # Round-robin through images for each selected occurrence
        for idx, occ in enumerate(selected_occurrences):
            tc = occ.get('timecode')
            if not tc:
                continue

            seconds = srt_timecode_to_seconds(tc)
            frame = seconds_to_frames(seconds, args.fps)

            if is_montage and len(filtered_images) >= 2:
                # Create rapid sequence montage: multiple images in quick succession
                montage_count += 1
                num_montage_images = min(montage_image_count, len(filtered_images))

                for m_idx in range(num_montage_images):
                    img = filtered_images[m_idx]
                    img_path = img.get('path', '')

                    if not img_path or not os.path.exists(img_path):
                        continue

                    montage_frame = frame + (m_idx * montage_clip_frames)
                    clips.append({
                        'frame': montage_frame,
                        'seconds': seconds + (m_idx * args.montage_clip_duration),
                        'path': os.path.abspath(img_path),
                        'name': f"{entity_name} - montage {m_idx + 1}/{num_montage_images}",
                        'entity': entity_name,
                        'occurrence_index': idx,
                        'image_index': m_idx,
                        'total_images': num_montage_images,
                        'is_montage_clip': True,
                        'montage_duration_frames': montage_clip_frames,
                        'image_meta': img,
                    })
            else:
                # Standard single-image clip
                img = filtered_images[idx % len(filtered_images)]
                img_path = img.get('path', '')

                if not img_path or not os.path.exists(img_path):
                    print(f"WARNING: Image not found: {img_path}", file=sys.stderr)
                    continue

                clips.append({
                    'frame': frame,
                    'seconds': seconds,
                    'path': os.path.abspath(img_path),
                    'name': f"{entity_name} - {img.get('filename', os.path.basename(img_path))}",
                    'entity': entity_name,
                    'occurrence_index': idx,
                    'image_index': idx % len(filtered_images),
                    'total_images': len(filtered_images),
                    'image_meta': img,
                })
    
    if not clips:
        print("ERROR: No valid clips to place", file=sys.stderr)
        sys.exit(1)
    
    # Sort by frame
    clips.sort(key=lambda x: x['frame'])
    
    print(f"Found {len(clips)} clips to place")
    
    # Assign tracks (stack overlapping clips on different tracks)
    duration_frames = seconds_to_frames(args.duration, args.fps)
    gap_frames = seconds_to_frames(args.gap, args.fps)
    
    # Track occupancy: track_end[track_idx] = frame when track becomes free
    base_track = 2  # Start on V2 (V1 typically has main video)
    track_end = {i: 0 for i in range(base_track, base_track + args.tracks)}
    
    placements = []
    skipped = 0
    
    for clip in clips:
        clip_start = clip['frame']
        # Use montage duration if this is a montage clip
        clip_duration = clip.get('montage_duration_frames', duration_frames)
        clip_end = clip_start + clip_duration

        # Find available track
        chosen_track = None
        # For montage clips, use smaller gap
        effective_gap = gap_frames // 4 if clip.get('is_montage_clip') else gap_frames

        for track_idx in range(base_track, base_track + args.tracks):
            if clip_start >= track_end[track_idx] + effective_gap:
                chosen_track = track_idx
                break

        if chosen_track is None:
            # All tracks busy, find one with earliest end
            earliest_track = min(track_end, key=track_end.get)
            if clip_start >= track_end[earliest_track]:
                chosen_track = earliest_track
            else:
                # For montage clips, try harder to place them (they're meant to be rapid)
                if not clip.get('is_montage_clip'):
                    print(f"  Skipping: {clip['name']} at {frames_to_timecode(clip_start, args.fps)} - all tracks occupied")
                skipped += 1
                continue

        placements.append({
            'frame': clip_start,
            'track': chosen_track,
            'path': clip['path'],
            'name': clip['name'],
            'duration_frames': clip_duration,
            'entity': clip.get('entity', ''),
            'image_meta': clip.get('image_meta', {}),
        })
        track_end[chosen_track] = clip_end

        # Show image rotation info
        img_idx = clip.get('image_index', 0)
        total_imgs = clip.get('total_images', 1)
        is_montage = clip.get('is_montage_clip', False)
        if is_montage:
            print(f"  V{chosen_track}: {clip['name']} at {frames_to_timecode(clip_start, args.fps)} (montage)")
        else:
            rotation_note = f" [image {img_idx + 1}/{total_imgs}]" if total_imgs > 1 else ""
            print(f"  V{chosen_track}: {clip['name']}{rotation_note} at {frames_to_timecode(clip_start, args.fps)}")

    print(f"\nPlacing {len(placements)} clips, skipped {skipped}")

    # Calculate rotation stats
    entities_with_rotation = set()
    for clip in clips:
        if clip.get('total_images', 1) > 1:
            entities_with_rotation.add(clip.get('entity'))

    # Calculate multi-image entities stats
    multi_image_entities = sum(1 for e in qualified_entities.values()
                               if len(e.get('images', [])) > 1 and len(e.get('occurrences', [])) > 1)

    print(f"\nImage variety:")
    print(f"  Multi-image entities: {multi_image_entities}")
    print(f"  Using rotation: {len(entities_with_rotation)}")
    if montage_count > 0:
        print(f"  Montage sequences: {montage_count} (rapid {args.montage_clip_duration}s clips)")

    # Frequency capping stats
    if capped_entities > 0:
        print(f"\nFrequency capping:")
        print(f"  Entities capped: {capped_entities}")
        print(f"  Max placements: {args.max_placements} (pervasive: {args.pervasive_max})")
        if pervasive_entities:
            print(f"  Pervasive entities: {', '.join(pervasive_entities[:5])}")
            if len(pervasive_entities) > 5:
                print(f"    ... and {len(pervasive_entities) - 5} more")

    # Log excluded entities
    if excluded_entities:
        print(f"\nExcluded {len(excluded_entities)} entities (below {args.min_match_quality} quality):")
        for exc in excluded_entities[:10]:  # Show first 10
            print(f"  - {exc['name']}: {exc['quality']}")
        if len(excluded_entities) > 10:
            print(f"  ... and {len(excluded_entities) - 10} more")
    
    # Generate XML
    xml_root = create_fcp_xml(placements, args.fps, args.timeline_name, args.duration)
    xml_string = prettify_xml(xml_root)
    
    # Write excluded entities log
    output_path = Path(args.output)
    excluded_file = output_path.with_suffix('.excluded.json')
    with open(excluded_file, 'w', encoding='utf-8') as f:
        json.dump({
            'min_quality': args.min_match_quality,
            'excluded_count': len(excluded_entities),
            'entities': excluded_entities
        }, f, indent=2)
    if excluded_entities:
        print(f"Excluded entities log: {excluded_file}")

    # Write output
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<!DOCTYPE xmeml>\n')
        # Remove the XML declaration from prettify (it adds one)
        lines = xml_string.split('\n')
        if lines[0].startswith('<?xml'):
            lines = lines[1:]
        f.write('\n'.join(lines))
    
    # Write attribution file for non-PD images used in the timeline
    if args.allow_non_pd:
        seen_filenames = set()
        attribution_lines = []
        for p in placements:
            meta = p.get('image_meta', {})
            cat = meta.get('category', '')
            fn = meta.get('filename', '')
            if cat == 'public_domain' or not fn or fn in seen_filenames:
                continue
            seen_filenames.add(fn)
            entity = p.get('entity', '')
            license_short = meta.get('license_short', cat)
            suggested = meta.get('suggested_attribution', '')
            attribution_lines.append(
                f"Entity: {entity} | File: {fn} | License: {license_short} | {suggested}"
            )

        if attribution_lines:
            attrib_path = output_path.with_suffix('.attribution.txt')
            with open(attrib_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(attribution_lines) + '\n')
            print(f"\nAttribution file: {attrib_path} ({len(attribution_lines)} non-PD images)",
                  file=sys.stderr)

    print(f"\nGenerated: {output_path.absolute()}")
    print(f"""
Next steps:
  1. Open DaVinci Resolve
  2. File > Import > Timeline... (or File > Import > XML)
  3. Select: {output_path.absolute()}
  4. The B-Roll timeline will be created with clips at correct positions
  5. Copy/paste clips to your main timeline, or use as reference
  
Note: If clips show as offline, right-click > Relink Selected Clips
""")


if __name__ == '__main__':
    main()
