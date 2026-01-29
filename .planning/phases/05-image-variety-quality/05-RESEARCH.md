# Phase 5: Image Variety & Quality Filtering - Research

**Researched:** 2026-01-29
**Domain:** Image rotation algorithms, quality-based filtering, Python data structures for tracking
**Confidence:** HIGH

## Summary

Phase 5 adds two distinct features to the existing B-roll pipeline: (1) image variety through rotation across multiple entity mentions, and (2) quality-based filtering during timeline generation. Research confirms both can be implemented using standard Python patterns without external libraries.

**Image rotation** is straightforward using existing data structures: the entities_map.json already has an ordered images list and occurrences list. The current round-robin logic (`filtered_images[idx % len(filtered_images)]` in generate_broll_xml.py line 351) cycles through images but doesn't track which image was used for which mention. Phase 5 requires tracking this metadata and adjusting download counts based on mention frequency.

**Quality filtering** leverages Phase 4's existing confidence-to-quality mapping (`derive_match_quality()` in disambiguation.py lines 172-206) which maps confidence scores (0-10) to quality levels (high/medium/low/none). The disambiguation metadata is already stored in entities_map.json under the "disambiguation" key with fields: confidence, match_quality, rationale, chosen_article. Timeline generation just needs to check match_quality against a configurable threshold.

**Primary recommendation:** Extend existing data structures and simple list indexing patterns rather than introducing new libraries. The round-robin rotation is already partially implemented; Phase 5 refines it with metadata tracking and dynamic download counts. Quality filtering is a simple threshold check during timeline generation with logging for excluded entities.

## Standard Stack

### Core

No external libraries required beyond what's already in the project:

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib | 3.10+ | List indexing, modulo arithmetic | Built-in, no dependencies needed |
| json | stdlib | Read/write metadata | Project already uses JSON for entities_map |
| Pillow (PIL) | 10.x+ | Image resolution/dimensions (optional) | Already in project for SVG conversion |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| collections.deque | stdlib | Efficient rotation if needed | Only if rotation logic becomes complex |
| typing | stdlib | Type hints for image tracking | Code clarity and IDE support |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Modulo arithmetic | collections.deque.rotate() | Deque adds abstraction without benefit for this use case |
| JSON metadata | Database (SQLite) | Overkill for single-file pipeline output |
| Pillow for dimensions | os.path.getsize() | File size alone insufficient for quality ranking |

**Installation:**

No additional packages required. Project already has Pillow for SVG conversion:
```bash
# Already in requirements.txt
pillow>=10.0.0
```

## Architecture Patterns

### Recommended Project Structure

```
tools/
├── download_entities.py    # Download with variable image counts
├── generate_broll_xml.py   # Timeline generation with quality filtering
└── disambiguation.py        # (unchanged - quality mapping already exists)

entities_map.json structure:
{
  "entities": {
    "EntityName": {
      "images": [...],        # Ordered list (best quality first)
      "occurrences": [...],   # Timeline mentions
      "image_usage": {        # NEW: Track which image used where
        "0": 0,               # occurrence index -> image index
        "1": 1
      },
      "disambiguation": {     # EXISTING: Phase 4 metadata
        "confidence": 8,
        "match_quality": "high"
      }
    }
  }
}
```

### Pattern 1: Quality-Ranked Image Rotation

**What:** Assign images to mentions in quality order, cycling back when exhausted

**When to use:** Multi-mention entities with multiple downloaded images

**Example:**
```python
# Current code (generate_broll_xml.py line 346-351)
for idx, occ in enumerate(occurrences):
    img = filtered_images[idx % len(filtered_images)]  # Round-robin

# Phase 5 enhancement with tracking
image_usage = {}  # occurrence_idx -> image_idx mapping
for idx, occ in enumerate(occurrences):
    img_idx = idx % len(filtered_images)  # Same rotation logic
    img = filtered_images[img_idx]
    image_usage[str(idx)] = img_idx  # Track assignment
```

**Source:** Existing codebase pattern, confirmed by [Python list rotation documentation](https://docs.python.org/3/library/collections.html)

### Pattern 2: Dynamic Download Count Based on Mentions

**What:** Fetch 5 images instead of 3 when entity has 3+ mentions

**When to use:** During download phase, before iteration starts

**Example:**
```python
# In download_entities.py, before calling download_entity()
mention_count = len(entity_data.get("occurrences", []))
if mention_count >= 3:
    images_to_download = min(5, mention_count)  # Cap at 5
else:
    images_to_download = 3  # Default for single/dual mentions
```

**Source:** [Round-robin assignment patterns](https://github.com/TheAlgorithms/Python/blob/master/scheduling/round_robin.py)

### Pattern 3: Quality Threshold Filtering with Logging

**What:** Skip entities below quality threshold, log exclusions to console and file

**When to use:** During timeline generation, before building clip placements

**Example:**
```python
# In generate_broll_xml.py main()
excluded_entities = []
min_quality = args.quality_threshold or "high"  # Default: high
quality_levels = {"high": 3, "medium": 2, "low": 1, "none": 0}

for entity_name, payload in entities.items():
    entity_quality = payload.get("disambiguation", {}).get("match_quality", "none")

    if quality_levels.get(entity_quality, 0) < quality_levels.get(min_quality, 3):
        excluded_entities.append({
            "entity": entity_name,
            "quality": entity_quality,
            "reason": f"Below threshold: {entity_quality} < {min_quality}"
        })
        continue  # Skip this entity

    # Process entity for timeline...

# Write exclusions log
if excluded_entities:
    with open(output_dir / "quality_exclusions.json", "w") as f:
        json.dump(excluded_entities, f, indent=2)
```

**Source:** [Quality control thresholding patterns](https://www.sc-best-practices.org/preprocessing_visualization/quality_control.html)

### Pattern 4: Image Quality Ranking (Claude's Discretion)

**What:** Rank images by quality for optimal first-mention assignment

**When to use:** After download, before storing in entities_map

**Option A - Wikipedia Order (Simplest):**
```python
# Wikipedia returns images in relevance order
# Assume first image is best, use as-is
images_list = downloaded_images  # Already ranked by Wikipedia API
```

**Option B - Resolution-Based (More Complex):**
```python
from PIL import Image

def rank_images_by_quality(image_paths):
    """Rank images by resolution (width * height)."""
    images_with_scores = []
    for path in image_paths:
        try:
            with Image.open(path) as img:
                width, height = img.size
                score = width * height
                images_with_scores.append((path, score))
        except Exception:
            images_with_scores.append((path, 0))  # Failed to load

    # Sort by score descending (best quality first)
    images_with_scores.sort(key=lambda x: x[1], reverse=True)
    return [path for path, _ in images_with_scores]
```

**Source:** [Pillow image dimensions](https://pillow.readthedocs.io/en/stable/reference/Image.html)

**Recommendation:** Start with Option A (Wikipedia order) since Wikipedia's image selection already prioritizes relevance and quality. Add Option B only if testing reveals quality issues.

### Anti-Patterns to Avoid

- **Don't reorder images randomly:** Breaks quality ranking assumption
- **Don't filter by quality during download:** Wastes API calls; filter at timeline generation
- **Don't track image usage with separate file:** Use entities_map.json to avoid synchronization issues
- **Don't use hard-coded quality mapping:** Make threshold configurable via CLI flag

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| List rotation with tracking | Custom circular buffer | Modulo arithmetic (`idx % len(list)`) | Built-in, single line, battle-tested |
| Image dimensions extraction | Custom binary parser | Pillow's `Image.open(path).size` | Handles all formats (JPG, PNG, SVG) |
| JSON atomic writes | Manual file write | `tempfile.NamedTemporaryFile()` + `os.replace()` | Prevents corruption from mid-write crashes |
| Quality level comparison | String comparison | Enum or dict mapping to ints | Type-safe, explicit ordering |

**Key insight:** Python's built-in data structures and standard library already solve rotation and filtering problems elegantly. The project's existing JSON-based architecture extends cleanly without introducing complexity.

## Common Pitfalls

### Pitfall 1: Off-by-One Errors in Image Rotation

**What goes wrong:** Using `idx % len(images)` with 1-indexed instead of 0-indexed lists causes incorrect image selection

**Why it happens:** Entity occurrence tracking may use 1-indexed cue numbers, but Python lists are 0-indexed

**How to avoid:** Always use enumerate() which provides 0-indexed iteration:
```python
for idx, occ in enumerate(occurrences):  # idx is always 0-indexed
    img = filtered_images[idx % len(filtered_images)]
```

**Warning signs:** First occurrence shows wrong image, or consistent off-by-one pattern in usage tracking

### Pitfall 2: Mutating Filtered Image List During Iteration

**What goes wrong:** Filtering images by quality/category while iterating causes skipped images or crashes

**Why it happens:** Modifying a list while iterating over it changes indices mid-loop

**How to avoid:** Filter once before the loop:
```python
# WRONG: Filter inside loop
for idx, occ in enumerate(occurrences):
    valid_images = [img for img in images if img['category'] == 'public_domain']
    img = valid_images[idx % len(valid_images)]  # Length changes each iteration!

# RIGHT: Filter once before loop
filtered_images = [img for img in images if img['category'] == 'public_domain']
if not filtered_images:
    continue  # Skip entity if no valid images
for idx, occ in enumerate(occurrences):
    img = filtered_images[idx % len(filtered_images)]
```

**Warning signs:** `IndexError: list index out of range` or images repeat unexpectedly

### Pitfall 3: Quality Threshold as String Comparison

**What goes wrong:** Comparing quality strings directly ("high" < "medium") gives wrong ordering

**Why it happens:** String comparison is alphabetical, not semantic: "low" > "high" alphabetically

**How to avoid:** Map quality levels to integers for comparison:
```python
# WRONG: String comparison
if entity_quality < min_quality:  # "low" < "high" is False (wrong!)
    skip_entity()

# RIGHT: Numeric comparison
quality_order = {"none": 0, "low": 1, "medium": 2, "high": 3}
if quality_order[entity_quality] < quality_order[min_quality]:
    skip_entity()
```

**Warning signs:** Medium-quality entities excluded when threshold is "low", or unexpected filter results

### Pitfall 4: Downloading 5 Images for All Entities

**What goes wrong:** Downloading 5 images for single-mention entities wastes API calls and disk space

**Why it happens:** Applying the "3+ mentions → 5 images" rule without checking mention count first

**How to avoid:** Check mention count before setting image count:
```python
# WRONG: Always download 5
images_per_entity = 5

# RIGHT: Dynamic based on mentions
occurrences = entity_data.get("occurrences", [])
if len(occurrences) >= 3:
    images_per_entity = 5
else:
    images_per_entity = 3  # Default for 1-2 mentions
```

**Warning signs:** Disk usage increases dramatically, download times double, many unused images in output directories

### Pitfall 5: Forgetting to Handle Missing disambiguation Key

**What goes wrong:** Timeline generation crashes when accessing `entity["disambiguation"]["match_quality"]` on entities processed before Phase 4

**Why it happens:** Entities downloaded without disambiguation (backward compatibility) lack this key

**How to avoid:** Use `.get()` with fallback:
```python
# WRONG: Direct access
match_quality = entity["disambiguation"]["match_quality"]

# RIGHT: Safe with fallback
match_quality = entity.get("disambiguation", {}).get("match_quality", "none")
```

**Warning signs:** `KeyError: 'disambiguation'` or `TypeError: 'NoneType' object is not subscriptable`

## Code Examples

Verified patterns from codebase and research:

### Round-Robin Image Assignment with Tracking

```python
# Source: Existing pattern in generate_broll_xml.py + enhancement
def assign_images_to_occurrences(
    entity_name: str,
    occurrences: List[dict],
    filtered_images: List[dict]
) -> Tuple[List[dict], dict]:
    """
    Assign images to occurrences in quality order with tracking.

    Returns: (placements, image_usage_metadata)
    """
    if not filtered_images:
        return ([], {})

    placements = []
    image_usage = {}  # occurrence_idx -> image_idx

    for idx, occ in enumerate(occurrences):
        # Round-robin with quality ranking
        img_idx = idx % len(filtered_images)
        img = filtered_images[img_idx]

        placements.append({
            "occurrence": idx,
            "timecode": occ.get("timecode"),
            "image_path": img.get("path"),
            "image_filename": img.get("filename")
        })

        image_usage[str(idx)] = img_idx

    return (placements, image_usage)
```

### Dynamic Image Count Based on Mentions

```python
# Source: download_entities.py enhancement
def calculate_images_to_download(entity_data: dict, default: int = 3) -> int:
    """
    Calculate how many images to download based on mention frequency.

    Rules:
    - 3+ mentions: download up to 5 images
    - 1-2 mentions: download default (3 images)
    """
    occurrences = entity_data.get("occurrences", [])
    mention_count = len(occurrences)

    if mention_count >= 3:
        # Download more images for variety, capped at 5
        return min(5, mention_count)
    else:
        # Use default for single/dual mentions
        return default
```

### Quality Threshold Filtering

```python
# Source: generate_broll_xml.py enhancement
def filter_entities_by_quality(
    entities: dict,
    min_quality: str = "high",
    output_dir: Path = None
) -> Tuple[dict, List[dict]]:
    """
    Filter entities by match quality threshold.

    Args:
        entities: Full entities dict from entities_map.json
        min_quality: Minimum quality level ("high", "medium", "low", "none")
        output_dir: Directory to write exclusions log (optional)

    Returns:
        (filtered_entities, excluded_entities_list)
    """
    quality_order = {"none": 0, "low": 1, "medium": 2, "high": 3}
    threshold = quality_order.get(min_quality, 3)  # Default to high

    filtered = {}
    excluded = []

    for entity_name, payload in entities.items():
        # Get quality from disambiguation metadata (Phase 4)
        entity_quality = payload.get("disambiguation", {}).get("match_quality", "none")
        quality_value = quality_order.get(entity_quality, 0)

        if quality_value >= threshold:
            filtered[entity_name] = payload
        else:
            excluded.append({
                "entity": entity_name,
                "quality": entity_quality,
                "confidence": payload.get("disambiguation", {}).get("confidence", 0),
                "reason": f"Quality {entity_quality} below threshold {min_quality}"
            })
            print(f"Excluding {entity_name}: {entity_quality} < {min_quality}")

    # Write exclusions log if output directory provided
    if output_dir and excluded:
        exclusions_path = output_dir / "quality_exclusions.json"
        with open(exclusions_path, "w", encoding="utf-8") as f:
            json.dump(excluded, f, indent=2)
        print(f"\nExcluded {len(excluded)} entities. See: {exclusions_path}")

    return (filtered, excluded)
```

### Image Quality Ranking (Optional Enhancement)

```python
# Source: Pillow documentation + custom logic
from PIL import Image
from pathlib import Path
from typing import List, Tuple

def rank_images_by_resolution(image_paths: List[Path]) -> List[Tuple[Path, int]]:
    """
    Rank images by resolution (width * height).

    Returns list of (path, resolution_score) tuples sorted descending.
    Higher resolution = better quality for this use case.
    """
    images_with_scores = []

    for path in image_paths:
        try:
            with Image.open(path) as img:
                width, height = img.size
                resolution = width * height
                images_with_scores.append((path, resolution))
        except Exception as e:
            # Failed to load image, assign 0 score
            print(f"Warning: Could not get dimensions for {path}: {e}")
            images_with_scores.append((path, 0))

    # Sort by resolution descending (best first)
    images_with_scores.sort(key=lambda x: x[1], reverse=True)
    return images_with_scores
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single image per entity | Round-robin rotation | Phase 5 (2026) | Better visual variety for multi-mention entities |
| Download fixed count (3) | Dynamic count based on mentions | Phase 5 (2026) | Efficiency: more images only when needed |
| Include all entities in timeline | Quality-based filtering | Phase 5 (2026) | Better accuracy: exclude low-confidence matches |
| No image usage tracking | Metadata tracks which image used where | Phase 5 (2026) | Enables future features (avoid repeats, user overrides) |

**Current best practices (2026):**
- **Quality-first assignment:** Best image for first mention is standard pattern
- **Configurable thresholds:** CLI flags for quality filtering provide flexibility
- **Logging exclusions:** Separate log file for filtered entities aids debugging
- **Metadata-driven:** Store rotation logic results in JSON for reproducibility

**Deprecated/outdated:**
- Static image counts (pre-Phase 5): Wastes resources for single-mention entities
- No quality filtering (pre-Phase 5): Timeline includes unreliable matches
- String-based quality comparison: Modern code uses numeric ordering

## Open Questions

Things that couldn't be fully resolved:

1. **Image Quality Ranking Method**
   - What we know: Wikipedia returns images in relevance order; Pillow can extract dimensions
   - What's unclear: Which ranking method produces best user experience? Resolution-based, file size-based, or Wikipedia order?
   - Recommendation: Start with Wikipedia order (simplest), add resolution ranking if user testing reveals issues. Defer file size ranking (requires additional computation).

2. **Scaling Image Count with Mentions**
   - What we know: 3+ mentions triggers 5 images (per CONTEXT.md)
   - What's unclear: Should this scale linearly (6 mentions = 6 images) or stay fixed at 5?
   - Recommendation: Fixed cap at 5 images for v1 (keeps API usage predictable). Scale linearly in v2 if users request more variety for very-frequent entities (e.g., main subject mentioned 20+ times).

3. **Quality Threshold Default Value**
   - What we know: CONTEXT.md specifies default is "high" (strict filtering)
   - What's unclear: Will this exclude too many entities in practice?
   - Recommendation: Implement "high" as default per spec, but monitor excluded entity counts in testing. Consider making threshold adaptive based on total entity count (e.g., lower threshold if <10 entities would pass).

## Sources

### Primary (HIGH confidence)

- **Existing codebase:** generate_broll_xml.py lines 340-356 (round-robin pattern), download_entities.py lines 673-873 (quality metadata storage), disambiguation.py lines 172-206 (quality mapping)
- [Python collections documentation](https://docs.python.org/3/library/collections.html) - deque rotation methods (not used, but confirmed modulo arithmetic is simpler)
- [Pillow Image module documentation](https://pillow.readthedocs.io/en/stable/reference/Image.html) - Image.size property for dimensions

### Secondary (MEDIUM confidence)

- [Python list rotation guide](https://www.geeksforgeeks.org/python/python-ways-to-rotate-a-list/) - Confirmed modulo arithmetic pattern
- [Round-robin scheduling examples](https://github.com/TheAlgorithms/Python/blob/master/scheduling/round_robin.py) - Dictionary tracking patterns
- [Quality control thresholding](https://www.sc-best-practices.org/preprocessing_visualization/quality_control.html) - MAD method for automatic thresholding (not applicable, but confirms configurable thresholds are standard)
- [Pillow image size tutorial](https://note.nkmk.me/en/python-opencv-pillow-image-size/) - Practical examples of extracting image dimensions

### Tertiary (LOW confidence)

- [Image quality assessment](https://pypi.org/project/image-quality/) - BRISQUE scoring library (overkill for this use case, but confirms resolution is primary quality metric)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - No new dependencies, uses existing Python stdlib + Pillow
- Architecture: HIGH - Extends existing patterns (round-robin, JSON metadata) without redesign
- Pitfalls: HIGH - Common issues identified from codebase patterns and Python list operations

**Research date:** 2026-01-29
**Valid until:** ~60 days (stable domain - rotation and filtering patterns unlikely to change)
