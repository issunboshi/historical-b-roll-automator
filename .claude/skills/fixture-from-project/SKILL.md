---
name: fixture-from-project
description: Generate a minimal but structurally-correct pytest fixture (entities_map.json or strategies_entities.json) from a real project output directory. Use when writing tests that need realistic entity/image data — prevents drift between fixtures and the shape the pipeline actually produces.
disable-model-invocation: true
---

# fixture-from-project

Generates a minimal pytest-ready JSON fixture from a real output directory so tests stay faithful to actual pipeline shapes.

## When to use this

- Writing a new test that exercises pipeline data (entities, images, occurrences)
- Updating an existing fixture after a schema change in `generate_xml.py`, `download_entities.py`, or `disambiguate_entities.py`
- Reproducing a bug that only appears with realistic data

## Inputs

Ask the user for:

1. **Source project dir** — e.g. `output/<video-name>/` containing a real `entities_map.json`, `strategies_entities.json`, or `enriched_entities.json`.
2. **Target fixture path** — where to write the stripped-down JSON (typically `tests/fixtures/<name>.json`).
3. **Shape variant** — which file type they want (entities_map / strategies / enriched).
4. **Size budget** — how many entities to keep (default 3). Pick a mix: one with multiple images and multiple occurrences, one "pervasive" background entity, one edge case (e.g. failed download or low match quality).

## Steps

1. Read the source JSON. Verify the top-level shape matches the file kind:
   - `entities_map.json` / `strategies_entities.json` / `enriched_entities.json` all key by entity name under an `entities` dict (see CLAUDE.md "Data Structures").
2. Select entities per the size budget. Prefer variety over density: include a `people`/`places` entity with full `images` (10-field metadata) and `occurrences`, a pervasive entity, and one edge case.
3. For each kept entity, retain the full nested structure (`images` as list of 10-field dicts, `occurrences` with timecodes, `disambiguation` metadata if present, `priority`, `entity_type`, `is_montage`, `montage_image_count`). Do not rename keys. Do not flatten.
4. Replace image `path` fields with placeholder paths that exist on the test machine — point to a tiny shared test asset like `tests/fixtures/assets/placeholder.jpg` rather than the real image paths. Keep `filename`, `source_url`, `category`, `license_short`, `suggested_attribution` as-is.
5. Preserve pre-existing top-level keys (e.g. `transcript_source`, `generated_at`, `srt_hash`) — tests may assert on them.
6. Write the fixture, pretty-printed with 2-space indent and sorted entity keys for deterministic diffs.
7. Print a short manifest: entity count, total images, total occurrences, entity types covered, so the user can decide whether to widen the budget.

## Schema reference (CLAUDE.md canonical)

```json
{
  "entities": {
    "Entity Name": {
      "entity_type": "people|places|events|concepts",
      "priority": 0.9,
      "images": [
        {
          "path": "...",
          "filename": "...",
          "category": "public_domain|cc_by|cc_by_sa|other_cc|unknown|restricted_nonfree",
          "license_short": "...",
          "license_url": "...",
          "source_url": "...",
          "title": "...",
          "author": "...",
          "usage_terms": "...",
          "suggested_attribution": "..."
        }
      ],
      "occurrences": [{"timecode": "HH:MM:SS,mmm", "cue_idx": 0}],
      "disambiguation": {"match_quality": "high|medium|low"}
    }
  }
}
```

## Output

- New / updated JSON fixture at the target path.
- Short summary (entity names kept, counts, omissions) printed to the conversation.
- A one-line reminder that the fixture must be regenerated if the canonical shape changes.

## Anti-patterns to avoid

- Do not invent synthetic entities from scratch. Source them from a real project dir.
- Do not drop the 10th image metadata field (`suggested_attribution`) — code in `generate_xml.py` reads it for the attribution file path.
- Do not rewrite the `entities` dict into a list — it is keyed by entity name, not a list. See memory and CLAUDE.md.
- Do not inline image binaries in the fixture.
