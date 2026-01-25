# Testing Patterns

**Analysis Date:** 2026-01-25

## Test Framework

**Runner:**
- Not detected in codebase

**Assertion Library:**
- Not detected in codebase

**Run Commands:**
- No test suite infrastructure found
- Manual testing via CLI: `python broll.py [command] [options]`
- Example: `python broll.py pipeline --srt video.srt --output-dir ./output --fps 24`

## Test File Organization

**Location:**
- No test files detected (no `test_*.py`, `*_test.py`, or `tests/` directory)
- Code testing appears to be manual/integration-based only

**Naming:**
- Not applicable

**Structure:**
- Not applicable

## Test Coverage

**Requirements:**
- No coverage enforcement detected
- No coverage reporting tools configured
- No test configuration files (pytest.ini, setup.cfg, tox.ini, etc.)

**View Coverage:**
- Not applicable

## Test Types

**Unit Tests:**
- Not implemented

**Integration Tests:**
- Manual integration via CLI commands
- Full pipeline testing: `python broll.py pipeline --srt [input.srt] --output-dir [output]`
- Step-by-step testing available:
  1. Extract: `python broll.py extract --srt video.srt --output entities.json`
  2. Download: `python broll.py download --map entities.json`
  3. XML generation: `python broll.py xml --map entities.json --output timeline.xml`

**E2E Tests:**
- Manual workflow through DaVinci Resolve import:
  1. Run pipeline to generate XML: `python broll.py pipeline --srt video.srt`
  2. Open DaVinci Resolve
  3. File > Import > Timeline...
  4. Select generated XML file
  5. Verify clips appear at correct timecodes on correct tracks

## Code Patterns for Testability

**File Operations:**
- All file I/O uses pathlib `Path` objects: `Path(args.input)`, `Path(args.output)`
- Files opened with explicit encoding: `open(path, 'r', encoding='utf-8')`
- Error checking for file existence: `if not path.exists(): print(...); sys.exit(1)`

**Configuration Loading (testable pattern in `broll.py`):**
```python
def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load config from YAML file, falling back to defaults."""
    config = dict(DEFAULT_CONFIG)  # Start with defaults

    path = config_path or find_config_file()
    if path and path.exists():
        # Load and merge file config
        ...
    return config
```

**Testable CLI structure:**
- Functions return exit codes (0/1): `return 0` or `return 1`
- Arguments passed via `argparse.Namespace`: `def cmd_extract(args: argparse.Namespace, config: Dict[str, Any]) -> int:`
- Configuration separated from execution: `config = load_config(args.config)`
- Command handlers can be tested with constructed Namespace objects

**Data Processing (testable pattern in `generate_broll_xml.py`):**
```python
def srt_timecode_to_seconds(tc: str) -> float:
    """Convert SRT timecode (HH:MM:SS,mmm) to seconds."""
    match = re.match(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})', tc)
    if not match:
        return 0.0
    h, m, s, ms = match.groups()
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
```
Pure function: takes input, returns output, no side effects.

```python
def seconds_to_frames(seconds: float, fps: float) -> int:
    """Convert seconds to frame count."""
    return int(round(seconds * fps))
```

```python
def frames_to_timecode(frames: int, fps: float) -> str:
    """Convert frame count to SMPTE timecode (HH:MM:SS:FF)."""
    fps_int = int(fps)
    total_seconds = frames // fps_int
    ff = frames % fps_int
    ss = total_seconds % 60
    mm = (total_seconds // 60) % 60
    hh = total_seconds // 3600
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"
```

## External Dependencies Used

**Requests library:**
- Used for HTTP requests to Wikipedia and LLM APIs in `srt_entities.py`, `wikipedia_image_downloader.py`
- Session management with custom user agent: `build_http_session(user_agent: str) -> requests.Session`
- Rate limiting: `REQUEST_DELAY_S`, `MAX_RETRIES`, `RETRY_BACKOFF_S` constants

**BeautifulSoup:**
- Used for HTML parsing in `wikipedia_image_downloader.py`
- Required in `requirements.txt`: `beautifulsoup4>=4.12.2,<5`

**XML generation:**
- Standard library `xml.etree.ElementTree` for FCP XML creation
- Standard library `xml.dom.minidom` for pretty-printing XML

**Parallel execution:**
- Standard library `concurrent.futures.ThreadPoolExecutor` for parallel downloads
- Thread locks for safe printing: `threading.Lock()` in `download_entities.py`

## Validation Patterns

**Input validation in CLI handlers (`broll.py`):**
```python
def cmd_extract(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    # Validation example
    script = resolve_script_path("srt_entities.py")  # Raises FileNotFoundError if not found
    ...
    out_path.parent.mkdir(parents=True, exist_ok=True)  # Ensure directory exists
    ...
    try:
        run_step("Extracting entities...", cmd)
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Entity extraction failed: {e}", file=sys.stderr)
        return 1
```

**Input validation in data processing (`generate_broll_xml.py`):**
```python
def main():
    # File existence check
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: File not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    # JSON validation
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    entities = data.get('entities', {})
    if not entities:
        print("ERROR: No 'entities' found in JSON", file=sys.stderr)
        sys.exit(1)

    # File existence validation for generated clips
    if not img_path or not os.path.exists(img_path):
        print(f"WARNING: Image not found: {img_path}", file=sys.stderr)
        continue
```

## Mocking Strategy

**Current approach:**
- No mocking framework installed or used
- Testing appears to be integration-based with real files and APIs

**Candidates for mocking if tests added:**
- HTTP requests to Wikipedia API (requests library)
- HTTP requests to LLM APIs (OpenAI, Ollama)
- File system operations (pathlib, os)
- Subprocess calls (subprocess module)

## Test Data

**Required test files:**
- Sample SRT transcript: `*.srt` file with timecodes and text
- Sample entities_map.json: JSON with entity data structure
- Sample images: Downloaded image files from Wikipedia

**Fixtures (if tests were implemented):**
- Mock SRT content strings for parsing tests
- Mock API response JSON from LLM and Wikipedia
- Temporary directories for file I/O tests

## Manual Testing Workflow

**To test entity extraction:**
```bash
python broll.py extract --srt path/to/video.srt --output entities_map.json \
  --provider openai --model gpt-4o-mini
```

**To test image download:**
```bash
python broll.py download --map entities_map.json --images-per-entity 3
```

**To test XML generation:**
```bash
python broll.py xml --map entities_map.json --output timeline.xml --fps 24
```

**To run full pipeline:**
```bash
python broll.py pipeline --srt path/to/video.srt --output-dir ./output --fps 24
```

**To verify configuration:**
```bash
python broll.py status
```

## Error Scenarios Covered

**CLI validation:**
- Missing required arguments (argparse handles)
- Missing files (explicit existence checks with sys.exit(1))
- Invalid paths (Path resolution with error messages)

**Data validation:**
- Missing required JSON keys: `entities.get('entities', {})`
- Invalid timecode format: regex matching with fallback to 0.0
- Missing image files: warning printed, clip skipped

**Subprocess handling:**
- Failed subprocess calls caught and reported: `except subprocess.CalledProcessError`
- Return codes checked for pipeline steps

---

*Testing analysis: 2026-01-25*
