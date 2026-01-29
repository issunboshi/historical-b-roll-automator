---
phase: 02-search-strategy-generation
plan: 03
subsystem: pipeline-orchestration
tags: [cli, broll.py, pipeline, integration, argparse]

# Dependency graph
requires:
  - phase: 02-search-strategy-generation
    plan: 01
    provides: generate_search_strategies.py script
  - phase: 01-enrichment-foundation
    provides: enriched_entities.json format
provides:
  - broll.py strategies subcommand with full CLI integration
  - 5-step pipeline: extract -> enrich -> strategies -> download -> xml
  - strategies_entities.json as pipeline intermediate file
affects: [Phase 3 filtering, Phase 4 disambiguation, end-to-end pipeline workflow]

key-files:
  created: []
  modified: [broll.py]

key-decisions:
  - "strategies step runs between enrich and download in pipeline sequence"
  - "--subject arg forwarded as --video-context to strategies step"
  - "strategies_entities.json replaces enriched_entities.json as input to download/XML"
  - "status command checks ANTHROPIC_API_KEY alongside OPENAI_API_KEY"
  - "--batch-size and --cache-dir exposed at pipeline level for strategies tuning"

patterns-established:
  - "cmd_strategies follows same pattern as other subcommands (script resolution, path handling, run_step)"
  - "Pipeline intermediate files: entities_map.json -> enriched_entities.json -> strategies_entities.json -> broll_timeline.xml"
  - "Each pipeline step creates Namespace args and calls respective cmd_* function"
  - "Status command maintains checklist of all pipeline scripts with existence checks"

# Metrics
duration: 3min
completed: 2026-01-29
---

# Phase 2 Plan 3: Pipeline Integration Summary

**Wired search strategy generator into broll.py as 5-step pipeline: extract -> enrich -> strategies -> download -> xml**

## What Was Built

### 1. Standalone Strategies Subcommand
Added `broll.py strategies` with complete CLI interface:
- **Required:** `--map` (path to enriched_entities.json)
- **Optional:** `--output` (default: strategies_entities.json in same dir)
- **Optional:** `--video-context` (for disambiguation)
- **Optional:** `--batch-size` (entities per LLM call, 5-10)
- **Optional:** `--cache-dir` (Wikipedia validation cache)

**Behavior:**
- Resolves generate_search_strategies.py from tools/ directory
- Validates enriched_entities.json exists before running
- Outputs strategies_entities.json with search_strategies field added
- Follows same error handling and output pattern as other subcommands

### 2. Integrated 5-Step Pipeline
Updated `cmd_pipeline` to run complete workflow:

**Step 1:** Extract entities (srt_entities.py)
- Input: video.srt
- Output: entities_map.json

**Step 2:** Enrich entities (enrich_entities.py)
- Input: entities_map.json, video.srt
- Output: enriched_entities.json

**Step 3:** Generate strategies (generate_search_strategies.py) **[NEW]**
- Input: enriched_entities.json
- Output: strategies_entities.json
- Video context: Forwarded from --subject arg
- Batch size: Forwarded from --batch-size arg
- Cache: Forwarded from --cache-dir arg

**Step 4:** Download images (download_entities.py)
- Input: strategies_entities.json **[CHANGED from enriched]**
- Output: Updated strategies_entities.json with images

**Step 5:** Generate XML (generate_broll_xml.py)
- Input: strategies_entities.json **[CHANGED from enriched]**
- Output: broll_timeline.xml

### 3. Status Command Integration
Updated `cmd_status` to show search strategy support:
- Added generate_search_strategies.py to script checklist
- Added ANTHROPIC_API_KEY environment check
- Now displays 6 pipeline scripts with existence verification

### 4. CLI Enhancements
**Pipeline command additions:**
- `--batch-size` (int): Entities per LLM call for strategies step
- `--cache-dir` (str): Wikipedia validation cache directory

**Help text updates:**
- Main help shows 5-step pipeline flow
- Docstring updated with enrich and strategies in workflow
- Success summary displays all 4 intermediate files

## Technical Implementation

### File Flow
```
video.srt
  -> entities_map.json
  -> enriched_entities.json
  -> strategies_entities.json [NEW intermediate]
  -> broll_timeline.xml
```

### cmd_strategies Function
```python
def cmd_strategies(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Generate LLM-powered Wikipedia search strategies."""
    script = resolve_script_path("generate_search_strategies.py")

    # Validate input
    map_path = Path(args.map)
    if not map_path.exists():
        return 1

    # Determine output (default: strategies_entities.json)
    out_path = args.output or map_path.parent / "strategies_entities.json"

    # Build command with optional args
    cmd = [sys.executable, str(script), "--map", str(map_path), "--out", str(out_path)]
    if args.video_context: cmd.extend(["--video-context", args.video_context])
    if args.batch_size: cmd.extend(["--batch-size", str(args.batch_size)])
    if args.cache_dir: cmd.extend(["--cache-dir", args.cache_dir])

    # Run with standard error handling
    run_step("Generating search strategies", cmd)
    return 0
```

### Pipeline Integration Pattern
Each step follows consistent pattern:
1. Create args Namespace with specific parameters
2. Call cmd_* function with args and config
3. Check return code
4. Return early with error message if non-zero

```python
# Step 3: Generate search strategies
strategies_args = argparse.Namespace(
    map=str(enriched_entities_path),
    output=str(strategies_entities_path),
    video_context=args.subject,  # Reuse --subject for context
    batch_size=getattr(args, 'batch_size', None),
    cache_dir=getattr(args, 'cache_dir', None),
)

result = cmd_strategies(strategies_args, config)
if result != 0:
    print("\nPipeline failed at: search strategy generation", file=sys.stderr)
    return result
```

## Verification Results

### CLI Structure ✓
```bash
$ python broll.py --help
Available commands:
  pipeline    Run the full pipeline: extract -> enrich -> strategies -> download -> xml
  extract     Extract entities from SRT transcript
  enrich      Enrich entities with priority scores and transcript context
  strategies  Generate LLM-powered Wikipedia search strategies [NEW]
  download    Download images for entities
  xml         Generate FCP XML from entities map
  status      Show configuration and check script availability
```

### Strategies Subcommand ✓
```bash
$ python broll.py strategies --help
usage: broll.py strategies [-h] --map MAP [--output OUTPUT]
                           [--video-context VIDEO_CONTEXT]
                           [--batch-size BATCH_SIZE] [--cache-dir CACHE_DIR]
```

### Pipeline Args ✓
```bash
$ python broll.py pipeline --help | grep -E "(batch-size|cache-dir)"
  --batch-size BATCH_SIZE       Entities per LLM call (5-10)
  --cache-dir CACHE_DIR         Wikipedia cache directory
```

### Status Command ✓
```bash
$ python broll.py status
Scripts:
  [OK] Entity extraction: .../srt_entities.py
  [OK] Entity enrichment: .../enrich_entities.py
  [OK] Search strategy generation: .../generate_search_strategies.py [NEW]
  [OK] Image download: .../download_entities.py
  [OK] XML generation: .../generate_broll_xml.py
  [OK] Wikipedia downloader: .../wikipedia_image_downloader.py

Environment:
  [WARN] OPENAI_API_KEY not set (required for OpenAI provider)
  [WARN] ANTHROPIC_API_KEY not set (required for search strategies) [NEW]
```

### Script Resolution ✓
```bash
$ python -c "from broll import resolve_script_path; print(resolve_script_path('generate_search_strategies.py'))"
/Users/cliffwilliams/code/b-roll-finder-app/tools/generate_search_strategies.py
```

## Success Criteria Met

- [x] `broll.py strategies` subcommand with --map, --output, --video-context, --batch-size, --cache-dir
- [x] Pipeline runs 5 steps (extract -> enrich -> strategies -> download -> xml)
- [x] strategies_entities.json created as intermediate file
- [x] Download and XML stages use strategies output
- [x] Status command shows generate_search_strategies.py
- [x] Status checks ANTHROPIC_API_KEY
- [x] All help text reflects 5-step pipeline

## Commits

| Task | Commit | Message |
|------|--------|---------|
| 1 | 729376c | feat(02-03): add strategies subcommand to broll.py |
| 2 | 48daa75 | feat(02-03): integrate strategies step into pipeline |
| 3 | 6750969 | feat(02-03): update status command for search strategies |

## Deviations from Plan

None - plan executed exactly as written.

## Next Phase Readiness

**Ready for Phase 2 Plan 4:** End-to-end testing with sample video

**Blockers:** None

**Notes:**
- Pipeline now fully wired but untested end-to-end
- ANTHROPIC_API_KEY must be set for strategies step to run
- --subject arg serves dual purpose: entity context + video context for disambiguation
- strategies_entities.json becomes the "source of truth" for download/XML stages

## Key Learnings

1. **Namespace pattern scales well:** Creating argparse.Namespace objects to pass between pipeline steps maintains clean separation while allowing incremental builds

2. **getattr for optional args:** Using `getattr(args, 'batch_size', None)` handles args that may not exist on Namespace object (avoids AttributeError)

3. **Status checklist pattern:** Maintaining scripts list makes it easy to verify all pipeline components are present

4. **Consistent error messages:** "Pipeline failed at: [step name]" pattern helps users identify exact failure point

5. **Output path defaults:** Following convention of same directory + new filename (strategies_entities.json) reduces CLI verbosity

## Future Considerations

- **Config file support:** batch_size and cache_dir could be added to broll_config.yaml for projects with consistent settings
- **Dry run mode:** `--dry-run` flag could show pipeline steps without executing
- **Resume support:** Pipeline could detect existing intermediate files and skip completed steps
- **Parallel execution:** Steps 1-2 are sequential, but future phases might enable strategies + download parallelization per entity
