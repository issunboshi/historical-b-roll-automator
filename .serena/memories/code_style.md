# Code Style Guidelines

## Python Version
Python 3.13.3

## Conventions
- Type hints encouraged for function signatures
- f-strings for string formatting
- Docstrings for public functions

## Config Import Pattern
Tools in `tools/` directory need this pattern to import config:
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402 - must come after sys.path modification
```

## Environment Variables
- Environment vars take precedence over INI file values
- Config auto-loads from `.wikipedia_image_downloader.ini`
- Key vars: ANTHROPIC_API_KEY, OPENAI_API_KEY, WIKIPEDIA_API_ACCESS_TOKEN

## Project Structure
```
broll.py              # Main CLI entry point
config.py             # Config loader
tools/                # Individual pipeline tools
  srt_entities.py
  enrich_entities.py
  generate_search_strategies.py
  disambiguation.py
  download_wikipedia_images.py
  generate_xml.py
  detect_montages.py
```
