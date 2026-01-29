# Phase 6: Quality Filtering CLI Integration - Research

**Researched:** 2026-01-29
**Domain:** Python CLI orchestration and argument passthrough
**Confidence:** HIGH

## Summary

This phase closes GAP-001 from the v1 milestone audit by exposing the existing `--min-match-quality` flag (already implemented in `generate_broll_xml.py`) through `broll.py`'s `pipeline` and `xml` commands. This is a CLI integration task, not a feature implementation task — the functionality already exists and just needs to be wired through the orchestrator.

The work follows an established pattern already present in the codebase from Phase 3 (priority filtering CLI integration). The same architectural approach applies: add argparse flags, pass them through subprocess calls, and maintain consistency between direct script invocation and orchestrator invocation.

Python's argparse module provides robust support for string choices via the `choices` parameter, which validates inputs and generates clear error messages. The subprocess passthrough pattern is straightforward: build command arrays with string-converted values.

**Primary recommendation:** Follow Phase 3 CLI passthrough pattern exactly. Add identical argparse configurations to both `p_pipeline` and `p_xml` subparsers, pass through `cmd_xml()` subprocess call, and include in `xml_args` Namespace within `cmd_pipeline()`.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| argparse | stdlib (Python 3.x) | CLI argument parsing | Python's built-in, official CLI solution; no external dependencies |
| subprocess | stdlib (Python 3.x) | Run subcommands | Standard library module for process orchestration |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| typing | stdlib (Python 3.5+) | Type hints | Already used in broll.py for Namespace, List, Dict types |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| argparse | click, typer | Adds external dependencies; broll.py already uses argparse consistently |
| subprocess | direct import | Breaking pattern; cmd_extract/cmd_download/cmd_enrich already use subprocess |

**Installation:**
No installation required — all stdlib modules.

## Architecture Patterns

### Recommended Project Structure
```
broll.py
├── subparser definitions (lines ~564-656)
│   ├── p_pipeline: full workflow CLI
│   ├── p_xml: XML generation CLI
│   └── p_download, p_extract, etc.
├── command handlers (lines ~135-473)
│   ├── cmd_xml(): orchestrates generate_broll_xml.py
│   └── cmd_pipeline(): orchestrates full pipeline including cmd_xml()
└── subprocess invocations
    └── run_step() utility
```

### Pattern 1: CLI Argument Definition with Choices
**What:** Use argparse add_argument with choices parameter for string option validation
**When to use:** When argument has fixed set of valid values (high, medium, low, none)
**Example:**
```python
# Source: https://docs.python.org/3/library/argparse.html
p_xml.add_argument('--min-match-quality', default='high',
                   choices=['high', 'medium', 'low', 'none'],
                   help='Minimum match quality to include (default: high)')
```

**Key details:**
- `choices` parameter validates input automatically
- Error messages list valid choices: "choose from 'high', 'medium', 'low', 'none'"
- `default` must be one of the valid choices
- String choices don't need type conversion

### Pattern 2: Subprocess Argument Passthrough
**What:** Build command array with string-converted argument values
**When to use:** When orchestrator script needs to pass CLI arguments to subprocess
**Example:**
```python
# Source: broll.py cmd_xml() lines 323-335
cmd = [
    sys.executable, str(script),
    str(map_path),
    "--output", str(out_path),
    "--fps", str(fps),
    "--timeline-name", timeline_name,
]

if allow_non_pd:
    cmd.append("--allow-non-pd")
```

**Key details:**
- Use list format, not shell strings (safer, no quoting issues)
- Convert numeric args to strings: `str(fps)`
- String args pass through directly: `timeline_name`
- Boolean flags: append flag name only if True
- Pass to `run_step()` which calls `subprocess.run(cmd, check=True)`

### Pattern 3: Namespace Construction for Internal Calls
**What:** Build argparse.Namespace manually when calling handler functions directly
**When to use:** When cmd_pipeline() calls cmd_xml() internally (not via subprocess)
**Example:**
```python
# Source: broll.py cmd_pipeline() lines 440-450
xml_args = argparse.Namespace(
    map=str(strategies_entities_path),
    output=str(xml_path),
    output_dir=None,
    fps=args.fps,
    duration=args.duration,
    gap=args.gap,
    tracks=args.tracks,
    allow_non_pd=args.allow_non_pd,
    timeline_name=args.timeline_name,
)

result = cmd_xml(xml_args, config)
```

**Key details:**
- Use `getattr(args, 'attr', default)` for optional arguments from parent
- String arguments pass through from parent args: `args.timeline_name`
- Numeric arguments pass through directly: `args.fps`
- Computed paths use str(): `str(xml_path)`

### Pattern 4: Consistent Flag Placement
**What:** Add new flags in logical groups, maintaining readability
**When to use:** When adding new arguments to existing subparsers
**Example:**
```python
# Source: broll.py p_pipeline definition, lines 574-590
# Existing quality/filtering flags
p_pipeline.add_argument("--allow-non-pd", action="store_true",
                        help="Include non-public-domain images")
p_pipeline.add_argument("--timeline-name", help="Name for the timeline")
# NEW: Add --min-match-quality here (logical grouping with --allow-non-pd)
```

**Key details:**
- Group related flags together (quality flags near each other)
- Place before delay/technical flags, after semantic flags
- Maintain consistent ordering between p_pipeline and p_xml

### Anti-Patterns to Avoid
- **Hard-coding flag values:** Don't set `--min-match-quality high` in subprocess cmd; pass user's value
- **Inconsistent defaults:** Phase 5 set default='high' in generate_broll_xml.py; must match in broll.py
- **Missing from both commands:** If added to `xml` but not `pipeline`, users get inconsistent experience
- **Forgetting cmd.extend():** String choices need `["--flag", value]` not just `["--flag"]`

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CLI parsing | Custom sys.argv parsing | argparse with choices | argparse validates choices, generates help text, provides clear errors |
| Process invocation | Shell command strings | subprocess.run() with list | Shell strings have security risks, quoting issues; list format is explicit |
| Argument validation | Manual if/elif chains | choices parameter | argparse raises clear error before code runs; auto-generates help text |
| Type conversion | Manual str() wrapping everywhere | Let argparse handle via type= | Cleaner, centralized; but Phase 6 uses strings so no conversion needed |

**Key insight:** Python's stdlib provides battle-tested solutions for CLI orchestration. The argparse + subprocess pattern handles edge cases (spaces in paths, special characters, error reporting) that hand-rolled solutions miss.

## Common Pitfalls

### Pitfall 1: Forgetting to Pass Through Both Locations
**What goes wrong:** Flag added to p_xml but not p_pipeline, or added to cmd_xml() but not xml_args Namespace
**Why it happens:** broll.py has two paths to generate_broll_xml.py: (1) direct via `broll.py xml`, (2) indirect via `broll.py pipeline` → cmd_pipeline() → cmd_xml()
**How to avoid:**
- Add flag to BOTH p_pipeline and p_xml subparsers
- Pass through in cmd_xml() subprocess call
- Include in xml_args Namespace in cmd_pipeline()
**Warning signs:**
- `broll.py xml --min-match-quality medium` works but `broll.py pipeline --min-match-quality medium` fails with "unrecognized argument"
- Or vice versa: pipeline works, xml fails

### Pitfall 2: Default Value Mismatch
**What goes wrong:** Different defaults in broll.py vs generate_broll_xml.py cause unexpected behavior
**Why it happens:** generate_broll_xml.py has `default='high'` but broll.py omits default, resulting in None
**How to avoid:**
- Match the default exactly: `default='high'`
- Verify with `getattr(args, 'min_match_quality', 'high')` when constructing Namespace
**Warning signs:**
- User runs `broll.py xml` without flag, gets different results than `python generate_broll_xml.py` without flag

### Pitfall 3: String Choice Not Passed Through cmd.extend()
**What goes wrong:** Using `cmd.append("--min-match-quality")` without value
**Why it happens:** Boolean flags use append(), but string choices need extend() with value
**How to avoid:**
```python
# WRONG: appends flag without value
cmd.append("--min-match-quality")

# CORRECT: extends with flag and value
cmd.extend(["--min-match-quality", args.min_match_quality])
```
**Warning signs:**
- Subprocess fails with "error: argument --min-match-quality: expected one argument"

### Pitfall 4: Forgetting help= Parameter
**What goes wrong:** New flag appears in --help but with no description
**Why it happens:** help= parameter is optional but recommended
**How to avoid:** Always include help= with clear, concise description matching generate_broll_xml.py's help text
**Warning signs:**
- `python broll.py xml --help` shows flag but no explanation

## Code Examples

Verified patterns from the codebase:

### Adding Flag to Subparser
```python
# Source: broll.py lines 574-590 (p_pipeline), adapted for Phase 6
p_pipeline.add_argument("--allow-non-pd", action="store_true",
                        help="Include non-public-domain images")
p_pipeline.add_argument("--timeline-name", help="Name for the timeline")
# NEW:
p_pipeline.add_argument("--min-match-quality", default='high',
                        choices=['high', 'medium', 'low', 'none'],
                        help='Minimum match quality to include (default: high)')
```

### Passing Through cmd_xml() Subprocess
```python
# Source: broll.py cmd_xml() lines 323-335, adapted for Phase 6
cmd = [
    sys.executable, str(script),
    str(map_path),
    "--output", str(out_path),
    "--fps", str(fps),
]

if allow_non_pd:
    cmd.append("--allow-non-pd")

# NEW: Pass through min_match_quality
cmd.extend(["--min-match-quality", args.min_match_quality])
```

### Including in xml_args Namespace
```python
# Source: broll.py cmd_pipeline() lines 440-450, adapted for Phase 6
xml_args = argparse.Namespace(
    map=str(strategies_entities_path),
    output=str(xml_path),
    output_dir=None,
    fps=args.fps,
    duration=args.duration,
    gap=args.gap,
    tracks=args.tracks,
    allow_non_pd=args.allow_non_pd,
    timeline_name=args.timeline_name,
    min_match_quality=getattr(args, 'min_match_quality', 'high'),  # NEW
)
```

### Phase 3 Reference Pattern (Priority Filtering)
```python
# Source: Phase 3 (03-02-PLAN.md), shows identical pattern for --min-priority
# This is the template to follow for --min-match-quality

# 1. Add to p_pipeline
p_pipeline.add_argument("--min-priority", type=float,
                        help="Minimum priority threshold for entity filtering (0.0 disables, default: 0.5)")

# 2. Add to p_download
p_download.add_argument("--min-priority", type=float,
                        help="Minimum priority threshold for entity filtering (0.0 disables, default: 0.5)")

# 3. Pass through cmd_download()
if hasattr(args, 'min_priority') and args.min_priority is not None:
    cmd.extend(["--min-priority", str(args.min_priority)])

# 4. Include in download_args Namespace
download_args = argparse.Namespace(
    min_priority=getattr(args, 'min_priority', None),
)
```

**Adaptation for Phase 6:**
- Replace `--min-priority` with `--min-match-quality`
- Replace `type=float` with `choices=['high', 'medium', 'low', 'none']` and `default='high'`
- Replace `str(args.min_priority)` with `args.min_match_quality` (already string, no conversion needed)
- Replace `None` default with `'high'` default
- Target cmd_xml() instead of cmd_download()

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual sys.argv parsing | argparse with choices | Python 3.2 (2011) | Validation, help generation, error messages all automatic |
| shell=True subprocess | list-form subprocess.run() | Python 3.5+ (2015) | Safer, no shell injection, explicit arguments |
| String concatenation for commands | List building with extend() | Best practice since subprocess introduction | No quoting issues, handles spaces in paths |

**Deprecated/outdated:**
- `optparse`: Deprecated since Python 2.7; replaced by argparse

## Open Questions

None. This is a straightforward CLI passthrough implementation following an established pattern.

## Sources

### Primary (HIGH confidence)
- Python argparse official documentation: https://docs.python.org/3/library/argparse.html
- Existing codebase (broll.py lines 323-335, 440-450, 574-590)
- Phase 3 implementation (03-02-PLAN.md) — identical pattern for --min-priority flag
- Phase 5 implementation (generate_broll_xml.py line 311) — target script's flag definition

### Secondary (MEDIUM confidence)
- [Argparse Tutorial](https://docs.python.org/3/howto/argparse.html) — official Python documentation
- Web search results on argparse patterns (2026)

### Tertiary (LOW confidence)
None required — all findings verified against official docs and existing code.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - stdlib modules, no external dependencies
- Architecture: HIGH - pattern already implemented in Phase 3, exact same approach applies
- Pitfalls: HIGH - derived from actual Phase 3 implementation and gap audit findings

**Research date:** 2026-01-29
**Valid until:** 2027-01-29 (argparse API is stable; no breaking changes expected)

---

## Research Notes

### Why This is HIGH Confidence

1. **Exact pattern exists:** Phase 3 (priority filtering) did identical work with --min-priority flag
2. **Target script complete:** generate_broll_xml.py already has --min-match-quality implemented
3. **Gap audit precise:** v1-MILESTONE-AUDIT.md identified exact line numbers and locations
4. **Stdlib stability:** argparse and subprocess are mature, stable APIs

### Implementation Checklist for Planner

Based on gap audit findings:

- [ ] Line ~578: Add `p_pipeline.add_argument('--min-match-quality', ...)`
- [ ] Line ~654: Add `p_xml.add_argument('--min-match-quality', ...)`
- [ ] cmd_xml() (~line 330): Add `cmd.extend(["--min-match-quality", args.min_match_quality])`
- [ ] cmd_pipeline() xml_args (~line 449): Add `min_match_quality=getattr(args, 'min_match_quality', 'high')`

### Verification Strategy

From Phase 3 verification:
```bash
# Verify flags appear in help
python broll.py pipeline --help | grep -A1 "min-match-quality"
python broll.py xml --help | grep -A1 "min-match-quality"

# Test actual usage
python broll.py xml --map output/strategies_entities.json --min-match-quality medium -o test.xml
python broll.py pipeline --srt test.srt --min-match-quality low --output-dir test_output
```

Should match behavior of direct invocation:
```bash
python generate_broll_xml.py output/strategies_entities.json --min-match-quality medium -o test.xml
```
