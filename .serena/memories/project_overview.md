# B-Roll Finder App

## Purpose
CLI tool for finding and downloading B-roll footage from Wikipedia based on SRT transcripts. Automates the process of extracting entities from video transcripts and finding relevant visual content.

## Architecture
- **Main Entry**: `broll.py` - orchestrates the full pipeline
- **Tool Scripts**: Located in `tools/` directory - each can run standalone or be called by broll.py
- **Config**: `.wikipedia_image_downloader.ini` - API keys loaded via `config.py` into os.environ

## Pipeline Steps
1. **extract** - Extract entities from SRT transcripts (`srt_entities.py`)
2. **enrich** - Enrich extracted entities (`enrich_entities.py`)
3. **strategies** - Generate search strategies (`generate_search_strategies.py`)
4. **disambiguate** - Disambiguate entities (`disambiguation.py`)
5. **download** - Download images from Wikipedia (`download_wikipedia_images.py`)
6. **xml** - Generate DaVinci Resolve XML (`generate_xml.py`)

## Key Tools
- `tools/srt_entities.py` - Extract entities from SRT transcripts
- `tools/enrich_entities.py` - Enrich extracted entities
- `tools/generate_search_strategies.py` - Generate search strategies
- `tools/disambiguation.py` - Disambiguate entities
- `tools/download_wikipedia_images.py` - Download images from Wikipedia
- `tools/generate_xml.py` - Generate DaVinci Resolve XML
- `tools/detect_montages.py` - Detect montage sequences

## Checkpointing
- `.broll_checkpoint.json` tracks completed steps and SRT hash
- `--resume` continues from last incomplete step
- `--from-step <step>` forces restart from specific step

## Dependencies
requests, beautifulsoup4, cairosvg, PyYAML, python-dotenv, anthropic, pydantic, Wikipedia-API, diskcache, tenacity
