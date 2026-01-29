---
phase: 05-image-variety-quality
verified: 2026-01-29T17:30:00Z
status: passed
score: 5/5 must-haves verified
---

# Phase 5: Image Variety & Quality Filtering Verification Report

**Phase Goal:** Entities mentioned multiple times use different images at each mention, and timeline generation filters by match quality
**Verified:** 2026-01-29T17:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | When entity mentioned multiple times and has multiple good images, different images used at different mentions | ✓ VERIFIED | Round-robin logic in generate_broll_xml.py line 377: `img = filtered_images[idx % len(filtered_images)]` ensures image rotation across occurrences |
| 2 | Metadata tracks which image used for which occurrence | ✓ VERIFIED | Clip metadata includes occurrence_index (line 393), image_index (line 394), and total_images (line 395) for each placed clip |
| 3 | Download stage fetches up to 5 images (instead of 3) for multi-mention entities | ✓ VERIFIED | download_entities.py lines 324-326: calculates effective_images = 5 when mention_count >= 3, passes to downloader via --limit flag (line 426) |
| 4 | Timeline generation has --min-match-quality flag to filter entities by match quality | ✓ VERIFIED | generate_broll_xml.py line 311: CLI argument with choices ['high', 'medium', 'low', 'none'], default 'high' |
| 5 | Entities below minimum match quality threshold excluded from timeline | ✓ VERIFIED | generate_broll_xml.py lines 337-351: builds qualified_entities dict by filtering based on QUALITY_ORDER comparison, uses qualified_entities for clip building (line 355) |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `tools/download_entities.py` | Dynamic image count logic based on mention count | ✓ VERIFIED | 912 lines, mention_count parameter (line 301), effective_images calculation (323-326), elevated_count tracking (687, 700, 740, 865) |
| `generate_broll_xml.py` | Image rotation and quality filtering for timeline generation | ✓ VERIFIED | 518 lines, QUALITY_ORDER constant (line 41), --min-match-quality argument (311-313), rotation metadata tracking (393-395), excluded_entities logging (471-492) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| download_entities.py | mention_count | len(occurrences) | ✓ WIRED | Lines 699, 738: `mention_count = len(payload.get("occurrences", []))` extracted and passed to download_entity() |
| download_entities.py | downloader subprocess | effective_images | ✓ WIRED | Line 426: `str(effective_images)` passed as --limit argument to wikipedia_image_downloader.py |
| download_entities.py | entities_map.json | disambiguation.match_quality | ✓ WIRED | Line 803: writes match_quality to payload["disambiguation"] which persists in entities_map.json |
| generate_broll_xml.py | disambiguation metadata | match_quality | ✓ WIRED | Lines 340-342: reads disambiguation.match_quality from entity payload for filtering |
| generate_broll_xml.py | filtered_images | round-robin rotation | ✓ WIRED | Line 377: `filtered_images[idx % len(filtered_images)]` implements rotation, metadata tracked in lines 393-395 |
| generate_broll_xml.py | qualified_entities | clip building loop | ✓ WIRED | Line 355: `for entity_name, payload in qualified_entities.items()` uses filtered entities for clip generation |

### Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| VAR-01: Use different images at different mentions when available | ✓ SATISFIED | Round-robin rotation via modulo operator (line 377) with metadata tracking |
| VAR-02: Track which images used for which occurrences | ✓ SATISFIED | Clip metadata includes occurrence_index, image_index, total_images (lines 393-395) |
| VAR-03: Download up to 5 images for multi-mention entities | ✓ SATISFIED | Dynamic image count: 5 for mention_count >= 3 (download_entities.py lines 324-326) |
| QUAL-06: Timeline generation filters by minimum match quality | ✓ SATISFIED | --min-match-quality flag with QUALITY_ORDER filtering (generate_broll_xml.py lines 311-351) |

### Anti-Patterns Found

None. Both files are substantive implementations with no TODO/FIXME markers, no stub patterns, and complete wiring between components.

### Human Verification Required

None. All success criteria are programmatically verifiable:
- Image rotation logic uses modulo arithmetic that can be traced in code
- Quality filtering uses dictionary comparison against QUALITY_ORDER constant
- Metadata tracking is explicit in clip dictionary construction
- Dynamic image count is passed directly to downloader subprocess

## Verification Details

### Truth 1: Different Images at Different Mentions

**Evidence:**
```python
# generate_broll_xml.py line 377
img = filtered_images[idx % len(filtered_images)]
```

The modulo operator (`idx % len(filtered_images)`) ensures that:
- When entity has 3 images and appears 5 times: uses image 0, 1, 2, 0, 1
- When entity has 1 image and appears 3 times: uses same image (0, 0, 0)
- Rotation cycles through available images in order

**Wiring verified:**
- Line 372: `for idx, occ in enumerate(occurrences)` iterates through all mentions
- Line 377: Selects image based on occurrence index
- Line 393-395: Tracks occurrence_index, image_index, total_images in metadata

### Truth 2: Metadata Tracking

**Evidence:**
```python
# generate_broll_xml.py lines 387-396
clips.append({
    'frame': frame,
    'seconds': seconds,
    'path': os.path.abspath(img_path),
    'name': f"{entity_name} - {img.get('filename', os.path.basename(img_path))}",
    'entity': entity_name,
    'occurrence_index': idx,                        # Which occurrence this is
    'image_index': idx % len(filtered_images),      # Which image was used
    'total_images': len(filtered_images),           # How many images available
})
```

Each clip stores:
- `occurrence_index`: Which mention this clip represents (0, 1, 2...)
- `image_index`: Which image from the entity's image list was used
- `total_images`: Total images available for rotation verification

**Console output:**
```python
# generate_broll_xml.py lines 449-452
rotation_note = f" [image {img_idx + 1}/{total_imgs}]" if total_imgs > 1 else ""
print(f"  V{chosen_track}: {clip['name']}{rotation_note} at {frames_to_timecode(clip_start, args.fps)}")
```

Real-time output shows rotation decisions: "[image 2/3]"

### Truth 3: Dynamic Image Count (5 for Multi-Mention Entities)

**Evidence:**
```python
# download_entities.py lines 323-326
effective_images = images_per_entity
if mention_count >= 3:
    effective_images = min(5, max(images_per_entity, 5))
    safe_print(f"[{current_idx}/{total_entities}]   Multi-mention entity ({mention_count}x): downloading {effective_images} images")
```

**Wiring to subprocess:**
```python
# download_entities.py lines 421-426
cmd = [
    sys.executable,
    str(downloader),
    search_term,
    "--limit",
    str(effective_images),  # Uses calculated effective_images, not default
    ...
]
```

**Statistics tracking:**
```python
# download_entities.py lines 687, 700, 740, 865
elevated_count = 0  # Track entities that got 5 images
if mention_count >= 3:
    elevated_count += 1
# In summary:
print(f"  Elevated (5 images): {elevated_count} entities")
```

### Truth 4: Quality Filtering Flag

**Evidence:**
```python
# generate_broll_xml.py lines 311-313
parser.add_argument('--min-match-quality', default='high',
                    choices=['high', 'medium', 'low', 'none'],
                    help='Minimum match quality to include (default: high)')
```

**Quality ordering:**
```python
# generate_broll_xml.py line 41
QUALITY_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}
```

**Help output verified:**
```
  --min-match-quality {high,medium,low,none}
                        Minimum match quality to include (default: high)
```

### Truth 5: Quality-Based Exclusion

**Evidence:**
```python
# generate_broll_xml.py lines 334-351
excluded_entities = []
min_quality_level = QUALITY_ORDER.get(args.min_match_quality, 3)

qualified_entities = {}
for entity_name, payload in entities.items():
    # Get match quality from disambiguation metadata
    disambiguation = payload.get('disambiguation', {})
    entity_quality = disambiguation.get('match_quality', 'high')
    entity_quality_level = QUALITY_ORDER.get(entity_quality, 0)

    if entity_quality_level < min_quality_level:
        excluded_entities.append({...})
        continue
    qualified_entities[entity_name] = payload
```

**Critical wiring:** Line 355 uses `qualified_entities`, not `entities`:
```python
for entity_name, payload in qualified_entities.items():
    images = payload.get('images', [])
    # ... build clips only from qualified entities
```

**Exclusion logging:**
```python
# generate_broll_xml.py lines 471-476
if excluded_entities:
    print(f"\nExcluded {len(excluded_entities)} entities (below {args.min_match_quality} quality):")
    for exc in excluded_entities[:10]:  # Show first 10
        print(f"  - {exc['name']}: {exc['quality']}")
```

**JSON output:**
```python
# generate_broll_xml.py lines 484-492
excluded_file = output_path.with_suffix('.excluded.json')
with open(excluded_file, 'w', encoding='utf-8') as f:
    json.dump({
        'min_quality': args.min_match_quality,
        'excluded_count': len(excluded_entities),
        'entities': excluded_entities
    }, f, indent=2)
```

## Summary

All 5 success criteria VERIFIED:

1. ✓ Different images at different mentions via round-robin rotation
2. ✓ Metadata tracks occurrence_index, image_index, total_images
3. ✓ Dynamic download: 5 images for entities with 3+ mentions
4. ✓ --min-match-quality flag filters timeline generation
5. ✓ Entities below threshold excluded from qualified_entities

**Code quality:**
- Both files compile without errors
- No TODO/FIXME/stub patterns found
- Substantive implementations (912 lines and 518 lines)
- Complete wiring between components verified
- Logging and statistics tracking in place

**Requirements satisfied:** VAR-01, VAR-02, VAR-03, QUAL-06

**Phase goal achieved:** Entities mentioned multiple times use different images at each mention, and timeline generation filters by match quality.

---

_Verified: 2026-01-29T17:30:00Z_
_Verifier: Claude (gsd-verifier)_
