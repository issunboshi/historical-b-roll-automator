# Visual Elements Marker Generation

**Date:** 2026-02-05
**Status:** Completed
**Archived:** 2026-02-10

## Purpose

Generate timeline markers from `visual_elements.json` for import into DaVinci Resolve. Markers indicate where visual elements (dates, quotes, numbers, processes, comparisons) appear in the transcript, allowing editors to see suggestions without pre-placed clips.

## CLI Interface

```bash
python tools/generate_markers.py visual_elements.json \
  --output markers.edl \
  --format edl \          # or xml (default: edl)
  --fps 24 \
  --timeline-name "B-Roll Markers"
```

### Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `input` | Yes | - | Path to `visual_elements.json` |
| `--output` | No | `<input_dir>/visual_markers.edl` | Output file path |
| `--format` | No | `edl` | Output format: `edl` or `xml` |
| `--fps` | No | `24` | Timeline frame rate |
| `--timeline-name` | No | `Visual Elements` | Timeline/sequence name |

## Marker Content

### Marker Name Format
```
TYPE: key_info
```

Examples:
- `DATE: 1857 - Serving in the army`
- `QUOTE: "By biting these cartridges we shall become infidels"`
- `NUMBER: 10 days later`
- `PROCESS: Arrest of Pandey (2 steps)`
- `COMPARISON: Company vs Sepoys`

### Marker Note/Comment
Full `source_text` from the visual element JSON.

### Color by Element Type

| Type | EDL Color | FCP XML Color ID |
|------|-----------|------------------|
| date | BLUE | 9 |
| quote | GREEN | 12 |
| number | YELLOW | 6 |
| process | RED | 2 |
| comparison | PURPLE | 3 |

## Output Formats

### EDL (CMX 3600)

```
TITLE: Visual Elements
FCM: NON-DROP FRAME

001  AX       V     C        00:00:00:00 00:00:00:01 00:00:00:00 00:00:00:01
* LOC: 00:00:00:00 BLUE     DATE: 1857 - Serving in the army
* SOURCE: It's 1857 and you're serving in the army of the East India Company.

002  AX       V     C        00:00:31:10 00:00:31:11 00:00:31:10 00:00:31:11
* LOC: 00:00:31:10 BLUE     DATE: 29 March - Mangalpandi made his choice
* SOURCE: Mangalpandi had served the company for years and on March 29th he made his choice.

003  AX       V     C        00:00:35:20 00:00:35:21 00:00:35:20 00:00:35:21
* LOC: 00:00:35:20 YELLOW   NUMBER: 10 days later
* SOURCE: He fired at his commanding officer and ten days later he hung.
```

### FCP XML (markers in sequence)

```xml
<xmeml version="5">
  <sequence>
    <name>Visual Elements</name>
    <rate><timebase>24</timebase></rate>
    <media>
      <video>
        <track>
          <marker>
            <name>DATE: 1857 - Serving in the army</name>
            <comment>It's 1857 and you're serving in the army...</comment>
            <in>0</in>
            <out>1</out>
            <color>9</color>
          </marker>
          <!-- more markers -->
        </track>
      </video>
    </media>
  </sequence>
</xmeml>
```

## Implementation

### File Structure

```
tools/generate_markers.py
```

### Key Functions

```python
def parse_visual_elements(json_path: Path) -> List[dict]
    """Load and validate visual_elements.json, return sorted list by timecode."""

def srt_timecode_to_frames(timecode: str, fps: float) -> int
    """Convert SRT timecode '00:00:31,440' to frame number."""

def frames_to_edl_timecode(frames: int, fps: float) -> str
    """Convert frame number to EDL timecode '00:00:31:10'."""

def get_marker_label(element: dict) -> str
    """Build 'TYPE: key_info' string from element data."""

def get_marker_color(element_type: str) -> Tuple[str, int]
    """Return (edl_color_name, xml_color_id) for element type."""

def generate_edl(elements: List[dict], fps: float, title: str) -> str
    """Generate CMX 3600 EDL string with marker comments."""

def generate_xml(elements: List[dict], fps: float, title: str) -> str
    """Generate FCP 7 XML with markers."""

def main(argv: Optional[List[str]] = None) -> int
    """CLI entry point."""
```

### Label Generation by Type

| Type | Label Format | Example |
|------|--------------|---------|
| date | `DATE: {date} - {event}` | `DATE: 1857 - Serving in the army` |
| quote | `QUOTE: "{text[:50]}..."` | `QUOTE: "By biting these cartridges..."` |
| number | `NUMBER: {value} {label}` | `NUMBER: 10 days later` |
| process | `PROCESS: {title} ({step_count} steps)` | `PROCESS: Arrest of Pandey (2 steps)` |
| comparison | `COMPARISON: {item1} vs {item2}` | `COMPARISON: Company vs Sepoys` |

## Pipeline Integration

### Updated Pipeline Steps

```
extract → enrich → strategies → disambiguate → download → markers → xml
                                                            ↑
                                                       NEW STEP
```

### Checkpoint

Step name: `markers`

### Integration in broll.py

```python
# After download step, before xml step
if current_step == "markers":
    visual_elements_path = output_dir / "visual_elements.json"
    if visual_elements_path.exists():
        markers_output = output_dir / "visual_markers.edl"
        run_tool(
            "generate_markers.py",
            str(visual_elements_path),
            "--output", str(markers_output),
            "--fps", str(fps),
            "--timeline-name", f"{timeline_name} - Markers"
        )
        checkpoint["markers"] = "complete"
```

## Testing

```bash
# Syntax check
python -m py_compile tools/generate_markers.py

# Test with sample data
python tools/generate_markers.py /path/to/visual_elements.json --format edl
python tools/generate_markers.py /path/to/visual_elements.json --format xml

# Verify EDL import in DaVinci Resolve
# File → Import → Timeline → select .edl file
```

## Future Enhancements

- Support for additional NLE formats (Premiere Pro marker CSV)
- Marker duration based on source_text length
- Grouping markers by type into separate tracks
- Interactive marker review/filtering before export
