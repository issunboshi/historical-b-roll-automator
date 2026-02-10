# Suggested Commands

## Running the Pipeline
```bash
# Run full pipeline on an SRT file
python broll.py pipeline --srt <file.srt> --out <output.json>

# Resume from checkpoint
python broll.py pipeline --resume

# Restart from a specific step
python broll.py pipeline --from-step disambiguate

# Show CLI help
python broll.py pipeline --help
```

## Development & Testing
```bash
# Quick syntax check
python -m py_compile <file.py>

# Verify CLI loads correctly
python broll.py pipeline --help

# Run individual tools standalone
python tools/srt_entities.py --help
python tools/download_wikipedia_images.py --help
```

## Pipeline Steps
Valid step names for `--from-step`:
- extract
- enrich
- strategies
- disambiguate
- download
- xml
