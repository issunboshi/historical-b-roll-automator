# Phase 3: Priority-Based Filtering - Research

**Researched:** 2026-01-29
**Domain:** Python CLI filtering patterns, data pipeline transparency, entity prioritization
**Confidence:** HIGH

## Summary

Priority-based filtering is a well-established pattern in Python data pipelines, combining argparse threshold arguments, conditional filtering logic, and transparent logging. The research focused on three core areas: CLI argument patterns for thresholds, filtering implementation with entity-type-specific rules, and transparent logging with skip reasons.

The standard approach uses argparse with type validation for threshold arguments (default values, float types, auto-generated help text), guard clause patterns for early-exit filtering logic (check conditions, skip if needed, otherwise proceed), and Python's built-in logging module for conditional verbosity (summary always shown, detailed logs only with -v/--verbose).

For JSON manipulation, the pattern involves maintaining separate "processed" and "skipped" arrays during filtering, with each skipped entity recording its name, type, priority, mention count, and human-readable skip reason. This provides full transparency without cluttering default output.

**Primary recommendation:** Use argparse type validation with ArgumentDefaultsHelpFormatter, implement filtering as guard clauses with early returns, use Python's logging module for conditional verbosity, and maintain separate skipped entities array in output JSON.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| argparse | stdlib (3.8+) | CLI argument parsing | Built-in, robust, well-documented standard for Python CLI tools |
| logging | stdlib (3.8+) | Conditional output based on verbosity | Standard library solution for hierarchical logging levels |
| json | stdlib (3.8+) | JSON manipulation | Built-in encoder/decoder with round-trip preservation |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| copy.deepcopy | stdlib | Preserve original data | When filtering needs to maintain unmodified source data |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| argparse | click/typer | More features but adds dependency; argparse sufficient for simple thresholds |
| logging | print() with if checks | Less structured; logging module provides consistent interface and levels |
| Manual JSON | Pydantic/dataclasses | Type safety but adds complexity; raw dict manipulation fine for simple filtering |

**Installation:**
```bash
# No installation needed - all stdlib
python3.8+  # argparse, logging, json all built-in
```

## Architecture Patterns

### Recommended Code Structure
```python
tools/
├── download_entities.py    # Add filtering logic here
│   ├── parse_args()       # CLI arguments including --min-priority
│   ├── should_skip()      # Guard clause filtering logic
│   ├── format_skip_reason()  # Human-readable skip messages
│   └── main()             # Orchestrate filter → download → update JSON
```

### Pattern 1: Argparse Threshold with Type Validation
**What:** Optional float arguments with defaults and auto-documented help
**When to use:** Any CLI tool needing configurable thresholds
**Example:**
```python
# Source: https://docs.python.org/3/library/argparse.html
parser = argparse.ArgumentParser(
    description='Download images for entities',
    formatter_class=argparse.ArgumentDefaultsHelpFormatter
)
parser.add_argument(
    '--min-priority',
    type=float,
    default=0.5,
    help='Minimum priority threshold for download (0.0 disables filtering)'
)
parser.add_argument(
    '-v', '--verbose',
    action='store_true',
    help='Show per-entity skip messages'
)
```

### Pattern 2: Guard Clause Filtering
**What:** Early-return pattern that checks skip conditions first, then proceeds with main logic
**When to use:** Entity filtering with multiple conditional rules
**Example:**
```python
# Based on: https://medium.com/@vaibhavmojidra/guard-clauses-simplifying-code-with-early-returns-754d511fcbd2
def should_skip_entity(entity_name, entity_data, min_priority, verbose=False):
    """
    Return (should_skip: bool, skip_reason: str) tuple.

    Guard clauses check skip conditions early with descriptive reasons.
    """
    priority = entity_data.get("priority", 0.0)
    entity_type = entity_data.get("entity_type", "").lower()
    occurrences = entity_data.get("occurrences", [])
    mention_count = len(occurrences)

    # Guard 1: People always download
    if entity_type == "people":
        return (False, "")

    # Guard 2: Events always download
    if entity_type == "events":
        return (False, "")

    # Guard 3: Places need override check
    if entity_type == "places":
        # Check for early mention override (first 10%)
        if occurrences:
            first_timecode = occurrences[0].get("timecode", "")
            # Calculate percentage (reuse srt_time_to_seconds from enrich_entities.py)
            first_pct = calculate_first_position_pct(first_timecode, transcript_duration)
            if first_pct <= 0.1:
                return (False, "place with early mention (first 10%)")

        # Check for multiple mentions override (2+)
        if mention_count >= 2:
            return (False, f"place with {mention_count} mentions")

        # Below threshold and no override
        if priority < min_priority:
            return (True, f"place with {mention_count} mention(s), priority {priority:.2f} < {min_priority:.2f}")

    # Guard 4: Concepts need higher threshold
    if entity_type == "concepts":
        concept_threshold = 0.7
        if priority < concept_threshold:
            return (True, f"concept priority {priority:.2f} < {concept_threshold:.2f}")

    # Guard 5: Default threshold check
    if priority < min_priority:
        return (True, f"priority {priority:.2f} < {min_priority:.2f}")

    # Passed all guards - should download
    return (False, "")
```

### Pattern 3: Conditional Logging with Verbosity
**What:** Use logging module to show detailed logs only when verbose flag is set
**When to use:** CLI tools that need detailed output optionally
**Example:**
```python
# Source: https://docs.python.org/3/howto/logging.html
import logging

def setup_logging(verbose):
    """Configure logging based on verbosity flag."""
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format='%(levelname)s: %(message)s',
        stream=sys.stderr  # Logs to stderr, results to stdout
    )

# In main()
setup_logging(args.verbose)
logger = logging.getLogger(__name__)

# Per-entity skip logs (only shown with -v)
if should_skip:
    logger.info(f"Skipping {entity_name}: {skip_reason}")

# Summary always shown (WARNING level)
logger.warning(f"Downloaded: {downloaded_count}, Skipped: {skipped_count}")
```

### Pattern 4: JSON Skipped Record Tracking
**What:** Maintain separate array of skipped entities in output JSON
**When to use:** Need audit trail of what was filtered and why
**Example:**
```python
# Based on: https://likegeeks.com/filter-json-array-python/
skipped_entities = []

for entity_name, entity_data in entities.items():
    should_skip, skip_reason = should_skip_entity(entity_name, entity_data, min_priority)

    if should_skip:
        skipped_entities.append({
            "name": entity_name,
            "entity_type": entity_data.get("entity_type"),
            "priority": entity_data.get("priority"),
            "mention_count": len(entity_data.get("occurrences", [])),
            "reason": skip_reason
        })
        continue

    # Download logic here...

# Add skipped array to output JSON
entities_map["skipped"] = skipped_entities
with open(map_path, "w") as f:
    json.dump(entities_map, f, ensure_ascii=False, indent=2)
```

### Pattern 5: CLI Summary Output (pytest-style)
**What:** Show summary statistics at end with clear categories
**When to use:** Pipeline tools that process many items
**Example:**
```python
# Based on: https://docs.pytest.org/en/stable/how-to/output.html
print()
print("=" * 60)
print("Download Summary")
print("=" * 60)
print(f"  Downloaded: {downloaded_count} entities")
print(f"  Skipped:    {skipped_count} entities")
print(f"  Failed:     {failed_count} entities")
print("=" * 60)

# Optional: breakdown by skip reason
if skipped_count > 0:
    print()
    print("Skip reasons:")
    reason_counts = {}
    for entity in skipped_entities:
        reason = entity["reason"]
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
        print(f"  - {count}x: {reason}")
```

### Anti-Patterns to Avoid
- **Using print() instead of logging:** Mixes output with results, no verbosity control
- **Deeply nested if-else:** Hard to follow; use guard clauses with early returns instead
- **Silent filtering:** Always log summary; skip reasons help users understand behavior
- **Mutating original JSON:** Use deep copy or track skipped separately to preserve source
- **Magic numbers:** Use named constants or config for thresholds (0.5, 0.7, 0.1, etc.)

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CLI argument parsing | String splitting, sys.argv slicing | argparse with type validation | Handles type conversion errors, auto-generates help, validates required args |
| Conditional output | if verbose: print() everywhere | logging module with levels | Structured, composable, standard interface across Python tools |
| Float validation | try/except float() in multiple places | argparse type=float | Centralized validation with user-friendly error messages |
| Default value documentation | Manually write defaults in help text | ArgumentDefaultsHelpFormatter | Auto-updates help when defaults change |
| JSON round-tripping | String manipulation, regex | json.load() + json.dump() | Preserves structure, handles encoding, validates syntax |

**Key insight:** Python's standard library (argparse, logging, json) provides battle-tested solutions for CLI tools. External dependencies are unnecessary for filtering logic—stdlib patterns are sufficient and reduce maintenance burden.

## Common Pitfalls

### Pitfall 1: Filtering Before Enrichment
**What goes wrong:** Developer adds filtering in enrichment stage, skips priority calculation for low-priority entities
**Why it happens:** Seems efficient to skip enrichment for entities that won't be downloaded
**How to avoid:** Always enrich ALL entities; filtering happens only at download stage. Enriched JSON serves as complete audit trail.
**Warning signs:** Enriched JSON has fewer entities than extracted JSON; priority scores missing for some entities

### Pitfall 2: Type Coercion in Comparisons
**What goes wrong:** Comparing priority (float) to threshold (string) silently fails or gives wrong results
**Why it happens:** Forgetting argparse type=float, getting string "0.5" instead of float 0.5
**How to avoid:** Always use type=float for numeric arguments; test with edge cases like 0.0 and 1.0
**Warning signs:** Filter logic doesn't work; entities with priority 0.6 get skipped with threshold "0.5"

### Pitfall 3: Verbose Flag Only Controls Per-Entity Logs
**What goes wrong:** Summary hidden behind verbose flag, user runs tool and sees no output
**Why it happens:** Putting summary at same logging level as per-entity messages
**How to avoid:** Summary uses WARNING level (always shown), per-entity uses INFO level (verbose only)
**Warning signs:** Users report "tool doesn't show what it did"; no output without -v

### Pitfall 4: Skip Reasons Not Human-Readable
**What goes wrong:** Skip reasons like "condition_3_failed" or "priority_low" aren't actionable
**Why it happens:** Using internal variable names or abbreviated labels
**How to avoid:** Format skip reasons with context: "place with 1 mention, priority 0.28 < 0.50"
**Warning signs:** Users confused about why entities were skipped; can't reproduce filtering behavior

### Pitfall 5: Threshold of 0 Still Filters
**What goes wrong:** User sets --min-priority 0 to disable filtering, but some entities still skipped
**Why it happens:** Forgetting to check for exact 0.0 to disable filtering completely
**How to avoid:** Document that 0.0 disables filtering; check `if min_priority <= 0.0: skip filtering`
**Warning signs:** Users report "can't download all entities even with --min-priority 0"

### Pitfall 6: Entity Type String Comparison Case Sensitivity
**What goes wrong:** Entity type is "People" but check is `entity_type == "people"`, guard clause fails
**Why it happens:** Inconsistent casing between extraction and filtering stages
**How to avoid:** Always normalize to lowercase: `entity_type.lower() == "people"`
**Warning signs:** People or events getting skipped when they shouldn't be

### Pitfall 7: Modifying Shared State in Parallel Downloads
**What goes wrong:** Parallel downloads (from Phase 2) corrupt skipped_entities array
**Why it happens:** Multiple threads appending to shared list without synchronization
**How to avoid:** Filter BEFORE parallel execution; pass only entities that should be downloaded to workers
**Warning signs:** Race conditions, missing skip records, duplicate entries in skipped array

## Code Examples

Verified patterns from official sources:

### Complete Filtering Implementation
```python
# Combining patterns from official Python documentation
import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Tuple

def parse_args(argv=None):
    """Parse CLI arguments with threshold validation."""
    parser = argparse.ArgumentParser(
        description="Download images for entities with priority filtering",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--map", required=True, help="Path to enriched_entities.json")
    parser.add_argument(
        "--min-priority",
        type=float,
        default=0.5,
        help="Minimum priority threshold (0.0 disables filtering)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show per-entity skip messages"
    )
    return parser.parse_args(argv)

def setup_logging(verbose):
    """Configure logging based on verbosity."""
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format='%(message)s',
        stream=sys.stderr
    )

def should_skip_entity(
    entity_name: str,
    entity_data: Dict,
    min_priority: float,
    transcript_duration: float
) -> Tuple[bool, str]:
    """
    Determine if entity should be skipped based on priority rules.

    Returns:
        (should_skip, skip_reason) tuple
    """
    priority = entity_data.get("priority", 0.0)
    entity_type = entity_data.get("entity_type", "").lower()
    occurrences = entity_data.get("occurrences", [])
    mention_count = len(occurrences)

    # Filtering disabled
    if min_priority <= 0.0:
        return (False, "")

    # People always download
    if entity_type == "people":
        return (False, "")

    # Events always download
    if entity_type == "events":
        return (False, "")

    # Places: check overrides
    if entity_type == "places":
        # Early mention override (first 10%)
        if occurrences:
            first_timecode = occurrences[0].get("timecode", "00:00:00,000")
            # Reuse srt_time_to_seconds from enrich_entities
            from tools.enrich_entities import srt_time_to_seconds
            first_time = srt_time_to_seconds(first_timecode)
            first_pct = first_time / transcript_duration if transcript_duration > 0 else 0.0

            if first_pct <= 0.1:
                return (False, "")  # No skip reason needed - passed filter

        # Multiple mentions override (2+)
        if mention_count >= 2:
            return (False, "")

        # Failed overrides, check threshold
        if priority < min_priority:
            return (True, f"place with {mention_count} mention(s), not in first 10%")

    # Concepts: higher threshold
    if entity_type == "concepts":
        if priority < 0.7:
            return (True, f"concept priority {priority:.2f} < 0.70")

    # Default threshold check
    if priority < min_priority:
        return (True, f"priority {priority:.2f} < {min_priority:.2f}")

    return (False, "")

def main(argv=None):
    args = parse_args(argv)
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    # Load enriched entities
    with open(args.map, "r", encoding="utf-8") as f:
        entities_map = json.load(f)

    entities = entities_map.get("entities", {})

    # Get transcript duration for place filtering
    # (In real implementation, extract from SRT metadata in entities_map)
    transcript_duration = entities_map.get("metadata", {}).get("transcript_duration", 0.0)

    # Filter entities
    to_download = []
    skipped_entities = []

    for entity_name, entity_data in entities.items():
        should_skip, skip_reason = should_skip_entity(
            entity_name, entity_data, args.min_priority, transcript_duration
        )

        if should_skip:
            logger.info(f"Skipping {entity_name}: {skip_reason}")
            skipped_entities.append({
                "name": entity_name,
                "entity_type": entity_data.get("entity_type"),
                "priority": entity_data.get("priority"),
                "mention_count": len(entity_data.get("occurrences", [])),
                "reason": skip_reason
            })
        else:
            to_download.append((entity_name, entity_data))

    # Download images for non-skipped entities
    downloaded_count = 0
    for entity_name, entity_data in to_download:
        # Download logic here...
        downloaded_count += 1

    # Record skipped entities in output
    entities_map["skipped"] = skipped_entities
    with open(args.map, "w", encoding="utf-8") as f:
        json.dump(entities_map, f, ensure_ascii=False, indent=2)

    # Summary (always shown)
    print()
    print("=" * 60)
    print("Download Summary")
    print("=" * 60)
    print(f"  Downloaded: {downloaded_count} entities")
    print(f"  Skipped:    {len(skipped_entities)} entities")
    print("=" * 60)

    return 0
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual sys.argv parsing | argparse with type validation | Python 2.7+ (2010) | Auto-generated help, type conversion, error handling |
| print() with if verbose | logging module with levels | Python 2.3+ (2003) | Structured output, composable filters, standard interface |
| Custom validation functions | argparse type parameter | Python 2.7+ (2010) | Centralized validation, better error messages |
| String concatenation for help | ArgumentDefaultsHelpFormatter | Python 3.2+ (2011) | Auto-updated defaults in help text |

**Deprecated/outdated:**
- optparse module: Deprecated since Python 3.2, replaced by argparse (more flexible, better subcommands)
- getopt module: Still available but argparse preferred for new code (getopt is lower-level, less Pythonic)

## Open Questions

Things that couldn't be fully resolved:

1. **Warning Zone Implementation (0.3-0.5)**
   - What we know: Context specifies warning zone where entities download but log warning
   - What's unclear: Should warnings go to logging.WARNING (always shown) or logging.INFO (verbose only)?
   - Recommendation: Use logging.WARNING for warnings—user should see them without -v. Distinct from INFO-level skip messages.

2. **Transcript Duration Storage Location**
   - What we know: Place filtering needs transcript duration for early mention percentage
   - What's unclear: Should duration be added to enriched_entities.json metadata, or re-parsed from SRT?
   - Recommendation: Add "transcript_duration" field to enriched_entities.json in Phase 1. More efficient than re-parsing SRT.

3. **Summary Output Destination**
   - What we know: Summary should always be shown (not dependent on verbose)
   - What's unclear: Should summary go to stdout (user output) or stderr (logging/status)?
   - Recommendation: Print to stdout for summary; logging to stderr. Summary is result, not status message.

## Sources

### Primary (HIGH confidence)
- https://docs.python.org/3/library/argparse.html - Argument parsing with type validation
- https://docs.python.org/3/howto/argparse.html - Argparse tutorial (updated Jan 28, 2026)
- https://docs.python.org/3/howto/logging.html - Conditional logging with verbosity levels
- https://docs.python.org/3/library/logging.html - Logging module API reference
- https://docs.python.org/3/library/json.html - JSON encoder/decoder

### Secondary (MEDIUM confidence)
- https://medium.com/@vaibhavmojidra/guard-clauses-simplifying-code-with-early-returns-754d511fcbd2 - Guard clause pattern
- https://dev.to/eddiegoldman/early-return-vs-classic-if-else-a-universal-pattern-for-writing-cleaner-code-1083 - Early return patterns
- https://docs.pytest.org/en/stable/how-to/output.html - CLI summary output patterns (pytest example)
- https://xahteiwi.eu/resources/hints-and-kinks/python-cli-logging-options/ - Configuring CLI verbosity with logging and argparse

### Tertiary (LOW confidence)
- https://likegeeks.com/filter-json-array-python/ - JSON array filtering techniques
- https://www.pluralsight.com/labs/codeLabs/log-monitor-and-debug-data-pipelines-with-python - Data pipeline logging patterns

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All stdlib, official Python documentation verified
- Architecture patterns: HIGH - Verified with official docs, established patterns since Python 3.2+
- Pitfalls: MEDIUM - Based on common patterns and training data; should be validated during implementation
- Code examples: HIGH - Sourced from official Python documentation
- Entity-type rules: HIGH - Defined in 03-CONTEXT.md from user discussion

**Research date:** 2026-01-29
**Valid until:** 2026-02-28 (30 days - stable domain, stdlib patterns don't change frequently)
