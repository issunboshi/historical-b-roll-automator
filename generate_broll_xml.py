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
    Convert a filesystem path to a proper file:// URL.
    
    Handles filenames that contain URL-encoded characters (like %2C for comma).
    These need to be re-encoded so %2C becomes %252C in the URL.
    """
    # Split into directory and filename
    dirname = os.path.dirname(filepath)
    basename = os.path.basename(filepath)
    
    # URL-encode the path components (quote encodes special chars including %)
    # safe='/' keeps forward slashes unencoded in the directory path
    encoded_dir = quote(dirname, safe='/')
    encoded_name = quote(basename, safe='')
    
    return f"file://localhost{encoded_dir}/{encoded_name}"


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
    file_registry = {}  # path -> file_id
    for p in placements:
        path = p['path']
        if path not in file_registry:
            file_id = f"masterclip-{generate_id()}"
            file_registry[path] = file_id
            
            # Create clip element in bin
            clip = ET.SubElement(bin_children, 'clip', id=file_id)
            ET.SubElement(clip, 'name').text = os.path.basename(path)
            ET.SubElement(clip, 'duration').text = str(p['duration_frames'])
            
            # Rate
            clip_rate = ET.SubElement(clip, 'rate')
            ET.SubElement(clip_rate, 'timebase').text = str(fps_int)
            ET.SubElement(clip_rate, 'ntsc').text = 'FALSE'
            
            # File reference
            file_elem = ET.SubElement(clip, 'file', id=f"file-{generate_id()}")
            ET.SubElement(file_elem, 'name').text = os.path.basename(path)
            ET.SubElement(file_elem, 'pathurl').text = path_to_file_url(path)
            ET.SubElement(file_elem, 'duration').text = str(p['duration_frames'])
            
            f_rate = ET.SubElement(file_elem, 'rate')
            ET.SubElement(f_rate, 'timebase').text = str(fps_int)
            ET.SubElement(f_rate, 'ntsc').text = 'FALSE'
            
            # Media info
            f_media = ET.SubElement(file_elem, 'media')
            f_video = ET.SubElement(f_media, 'video')
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
            masterclip_id = file_registry.get(p['path'])
            if masterclip_id:
                ET.SubElement(clipitem, 'masterclipid').text = masterclip_id
            
            # Clip name
            clip_name = p.get('name', os.path.basename(p['path']))
            ET.SubElement(clipitem, 'name').text = clip_name
            
            # Duration (clip duration)
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
            
            # File reference (still needed for Resolve to find the media)
            file_elem = ET.SubElement(clipitem, 'file', id=f"file-{generate_id()}")
            ET.SubElement(file_elem, 'name').text = os.path.basename(p['path'])
            ET.SubElement(file_elem, 'pathurl').text = path_to_file_url(p['path'])
            
            # File rate
            f_rate = ET.SubElement(file_elem, 'rate')
            ET.SubElement(f_rate, 'timebase').text = str(fps_int)
            ET.SubElement(f_rate, 'ntsc').text = 'FALSE'
            
            # File duration (for stills, use clip duration)
            ET.SubElement(file_elem, 'duration').text = str(p['duration_frames'])
            
            # Media info
            f_media = ET.SubElement(file_elem, 'media')
            f_video = ET.SubElement(f_media, 'video')
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

    # Build list of clips with timecodes
    clips = []
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
        
        # Round-robin through images for each occurrence
        for idx, occ in enumerate(occurrences):
            tc = occ.get('timecode')
            if not tc:
                continue
            
            img = filtered_images[idx % len(filtered_images)]
            img_path = img.get('path', '')
            
            if not img_path or not os.path.exists(img_path):
                print(f"WARNING: Image not found: {img_path}", file=sys.stderr)
                continue
            
            seconds = srt_timecode_to_seconds(tc)
            frame = seconds_to_frames(seconds, args.fps)
            
            clips.append({
                'frame': frame,
                'seconds': seconds,
                'path': os.path.abspath(img_path),
                'name': f"{entity_name} - {img.get('filename', os.path.basename(img_path))}",
                'entity': entity_name,
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
        clip_end = clip_start + duration_frames
        
        # Find available track
        chosen_track = None
        for track_idx in range(base_track, base_track + args.tracks):
            if clip_start >= track_end[track_idx] + gap_frames:
                chosen_track = track_idx
                break
        
        if chosen_track is None:
            # All tracks busy, find one with earliest end
            earliest_track = min(track_end, key=track_end.get)
            if clip_start >= track_end[earliest_track]:
                chosen_track = earliest_track
            else:
                print(f"  Skipping: {clip['name']} at {frames_to_timecode(clip_start, args.fps)} - all tracks occupied")
                skipped += 1
                continue
        
        placements.append({
            'frame': clip_start,
            'track': chosen_track,
            'path': clip['path'],
            'name': clip['name'],
            'duration_frames': duration_frames,
        })
        track_end[chosen_track] = clip_end
        
        print(f"  V{chosen_track}: {clip['name']} at {frames_to_timecode(clip_start, args.fps)}")

    print(f"\nPlacing {len(placements)} clips, skipped {skipped}")

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
