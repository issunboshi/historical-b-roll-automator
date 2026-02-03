# B-Roll Finder App

## Architecture
- Main CLI: `broll.py` - orchestrates full pipeline (extract → enrich → strategies → disambiguate → download → xml)
- Tool scripts in `tools/` directory - each can run standalone or be called by broll.py
- Key tools: `download_wikipedia_images.py`, `generate_xml.py`, `download_entities.py`, `disambiguation.py`
- Config: `.wikipedia_image_downloader.ini` - API keys and output_dir loaded via `config.py` into os.environ

## Config Loading
- `import config` at top of entry points auto-loads API keys from INI file
- Tools in `tools/` need: `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` before `import config`
- Environment vars take precedence over INI file values

## Pipeline Checkpointing
- `.broll_checkpoint.json` tracks completed steps and SRT hash
- `--resume` continues from last incomplete step
- `--from-step <step>` forces restart from specific step
- Steps: extract, enrich, strategies, disambiguate, download, xml

## Testing
- `python -m py_compile <file>` - quick syntax check
- `python broll.py pipeline --help` - verify CLI loads correctly

## API Keys (in .wikipedia_image_downloader.ini)
- ANTHROPIC_API_KEY - for disambiguation and search strategies
- OPENAI_API_KEY - for entity extraction (provider=openai)
- WIKIPEDIA_API_ACCESS_TOKEN - for authenticated Wikipedia API access (5000 req/hr vs 500 unauth)
