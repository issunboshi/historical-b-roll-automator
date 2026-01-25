# Testing Patterns

**Analysis Date:** 2026-01-25

## Test Framework

**Runner:**
- No test framework installed (pytest, unittest, nose not detected)
- Python standard library used for structural organization only

**Assertion Library:**
- Not detected in codebase
- Manual assertion via explicit checks and error handling

**Run Commands:**
- No automated test suite; manual testing via CLI commands only
- Example: `python broll.py pipeline --srt video.srt --output-dir ./output --fps 24`
- Status check: `python broll.py status`

## Test File Organization

**Location:**
- No test files detected (no `test_*.py`, `*_test.py`, `tests/` directory)
- Code testing appears to be manual/integration-based only
- No `pytest.ini`, `setup.cfg`, `tox.ini` or similar configuration

**Naming:**
- Not applicable (no test files exist)

**Structure:**
- Not applicable (no test files exist)

## Test Structure

**Current approach:**
- Integration testing via CLI commands
- Manual verification of outputs
- No automated test harness

**Testable patterns identified:**

Pure functions without side effects (easily testable):
- `srt_timecode_to_seconds()` in `generate_broll_xml.py` - converts timecode strings to float seconds
- `seconds_to_frames()` in `generate_broll_xml.py` - converts seconds to frame count
- `frames_to_timecode()` in `generate_broll_xml.py` - converts frames to SMPTE timecode
- `_srt_time_to_seconds()` in `srt_entities.py` - converts SRT format to seconds
- `_normalize_entity_name()` in `srt_entities.py` - normalizes entity names
- `path_to_file_url()` in `generate_broll_xml.py` - converts filesystem paths to file:// URLs

## Mocking

**Framework:**
- No mocking framework installed (unittest.mock, pytest-mock, responses not detected)

**Patterns (if tests were implemented):**
- HTTP requests to Wikipedia API would need mocking via `unittest.mock` or `responses`
- HTTP requests to LLM APIs (OpenAI, Ollama) would need mocking
- File system operations would use temporary directories via `tempfile` module
- Subprocess calls would use mocking to capture command execution
- Configuration loading would use test YAML files in temporary directories

**Candidates for mocking:**
- `requests.Session` and `requests.get()` calls in `srt_entities.py`, `wikipedia_image_downloader.py`
- `subprocess.run()` calls in `broll.py`, `tools/download_entities.py`
- `open()` for file I/O operations
- Path operations: `Path.exists()`, `Path.mkdir()`

## Fixtures and Factories

**Test Data (would be needed):**
- Sample SRT transcript file with valid timecodes
- Sample `entities_map.json` with entity data structure
- Sample Wikipedia image filenames and metadata
- Expected output XML for comparison

**Location (if implemented):**
- `tests/fixtures/` or `tests/data/` directory
- Sample files: `test_data.srt`, `sample_entities.json`, `expected_output.xml`

**Example fixture structure:**
```python
# Sample SRT content for testing parse_srt()
TEST_SRT = """1
00:00:00,000 --> 00:00:05,000
Opening narration about history

2
00:00:05,000 --> 00:00:10,000
Speaker 1
More content here
"""

# Sample entities_map.json structure
SAMPLE_ENTITIES_MAP = {
    "entities": {
        "Napoleon Bonaparte": {
            "entity_type": "people",
            "images": [
                {"path": "images/napoleon_1.jpg", "license": "PD"}
            ],
            "occurrences": [
                {"cue_index": 1, "start": "00:00:00,000", "end": "00:00:05,000"}
            ]
        }
    }
}
```

## Coverage

**Requirements:**
- None enforced
- No coverage reporting tools configured

**View Coverage:**
- Not applicable

## Test Types

**Unit Tests:**
- Not implemented
- Candidates for unit testing: conversion functions, name normalization, entity parsing
- Example test target: `srt_timecode_to_seconds()`
  ```python
  assert srt_timecode_to_seconds("00:01:30,500") == 90.5
  assert srt_timecode_to_seconds("01:00:00,000") == 3600.0
  assert srt_timecode_to_seconds("invalid") == 0.0  # fallback
  ```

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

## Common Patterns

**Async Testing:**
- Not applicable (no async code in codebase)

**Error Testing:**
- Manual validation via missing file handling:
  ```bash
  python broll.py extract --srt nonexistent.srt  # Tests file existence check
  python broll.py download --map nonexistent.json  # Tests file existence check
  ```
- Error messages printed to stderr and return codes checked (0 for success, 1 for failure)

**Example error handling pattern from `broll.py`:**
```python
def cmd_extract(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Run entity extraction from SRT."""
    script = resolve_script_path("srt_entities.py")

    # Output path setup
    if args.output:
        out_path = Path(args.output)
    elif args.output_dir:
        out_path = Path(args.output_dir) / "entities_map.json"
    else:
        out_path = Path("entities_map.json")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Build command
    cmd = [sys.executable, str(script), "--srt", str(args.srt), ...]

    try:
        run_step("Extracting entities from transcript", cmd)
        print(f"\nEntities saved to: {out_path.absolute()}")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Entity extraction failed: {e}", file=sys.stderr)
        return 1
```

## Code Patterns for Testability

**File Operations (testable pattern in `generate_broll_xml.py`):**
```python
def main():
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: File not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    entities = data.get('entities', {})
    if not entities:
        print("ERROR: No 'entities' found in JSON", file=sys.stderr)
        sys.exit(1)
```

**Configuration Loading (testable pattern in `broll.py`):**
```python
def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load config from YAML file, falling back to defaults."""
    config = dict(DEFAULT_CONFIG)  # Start with defaults

    path = config_path or find_config_file()
    if path and path.exists():
        # Load and merge file config
        try:
            with open(path, "r", encoding="utf-8") as f:
                file_config = yaml.safe_load(f) or {}
            for key, value in file_config.items():
                if isinstance(value, dict) and key in config:
                    config[key].update(value)
                else:
                    config[key] = value
        except Exception as e:
            print(f"Warning: Failed to load config from {path}: {e}", file=sys.stderr)

    return config
```
Testable: defaults applied, file loading is optional, exceptions handled gracefully

**CLI structure (testable):**
```python
def cmd_extract(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Run entity extraction from SRT."""
    # Functions return exit codes (0/1)
    # Arguments passed via argparse.Namespace
    # Configuration separated from execution
    # Can be tested with constructed Namespace objects
```

**Data Processing (testable pattern):**
```python
def srt_timecode_to_seconds(tc: str) -> float:
    """Convert SRT timecode (HH:MM:SS,mmm) to seconds."""
    match = re.match(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})', tc)
    if not match:
        return 0.0
    h, m, s, ms = match.groups()
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
```
Pure function: takes input, returns output, no side effects

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

**Thread-safe operations (testable pattern in `tools/download_entities.py`):**
```python
_print_lock = threading.Lock()

def safe_print(*args, **kwargs):
    """Thread-safe print function."""
    with _print_lock:
        print(*args, **kwargs)
```
Thread safety properly managed; can be tested for race conditions with concurrent threads

## Validation Patterns

**Input validation in CLI handlers:**
```python
# File existence check
if not map_path.exists():
    print(f"Error: entities_map not found: {map_path}", file=sys.stderr)
    return 1
```

**Input validation in data processing:**
```python
# JSON structure validation
entities = data.get('entities', {})
if not entities:
    print("ERROR: No 'entities' found in JSON", file=sys.stderr)
    sys.exit(1)

# File existence validation for generated clips
if not img_path or not os.path.exists(img_path):
    print(f"WARNING: Image not found: {img_path}", file=sys.stderr)
    continue
```

**Subprocess handling:**
```python
try:
    subprocess.run(cmd, check=True, capture_output=capture_output)
except subprocess.CalledProcessError as e:
    print(f"Step failed: {e}", file=sys.stderr)
    return 1
```

## External Dependencies Used

**Requests library:**
- Used for HTTP requests to Wikipedia and LLM APIs in `srt_entities.py`, `wikipedia_image_downloader.py`
- Session management with custom user agent: `build_http_session(user_agent: str) -> requests.Session`
- Rate limiting via constants: `REQUEST_DELAY_S`, `MAX_RETRIES`, `RETRY_BACKOFF_S`
- Proper retry logic with exponential backoff

**BeautifulSoup:**
- Used for HTML parsing in `wikipedia_image_downloader.py`
- Required in `requirements.txt`: `beautifulsoup4>=4.12.2,<5`
- Parses Wikipedia page content for image metadata

**XML generation:**
- Standard library `xml.etree.ElementTree` for FCP 7 XML creation in `generate_broll_xml.py`
- Standard library `xml.dom.minidom` for pretty-printing XML output

**Parallel execution:**
- Standard library `concurrent.futures.ThreadPoolExecutor` for parallel downloads in `tools/download_entities.py`
- Thread locks for safe printing: `threading.Lock()` in `download_entities.py`
- Proper synchronization to avoid interleaved console output

**Configuration:**
- `PyYAML>=6.0,<7` for optional YAML config loading
- `python-dotenv>=1.0.0,<2` for environment variable loading
- `cairosvg>=2.7.0,<3` for SVG to PNG conversion

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

**To verify configuration and script availability:**
```bash
python broll.py status
```

**To test parallel downloads:**
```bash
python broll.py pipeline --srt video.srt -j 4 --output-dir ./output
```

## Error Scenarios Covered

**CLI validation:**
- Missing required arguments: handled by argparse
- Missing files: explicit existence checks with `sys.exit(1)`
- Invalid paths: Path resolution with descriptive error messages
- Script not found: `FileNotFoundError` from `resolve_script_path()`

**Data validation:**
- Missing required JSON keys: `entities.get('entities', {})` with safe fallback
- Invalid timecode format: regex matching with fallback to 0.0 seconds
- Missing image files: warning printed to stderr, clip skipped gracefully
- Empty entity lists: handled with empty collection initialization

**Subprocess handling:**
- Failed subprocess calls caught: `except subprocess.CalledProcessError`
- Return codes checked for each pipeline step
- Error messages propagated to caller via return codes (0/1)

**Network/API failures (in `srt_entities.py`, `wikipedia_image_downloader.py`):**
- Retry logic with exponential backoff
- Rate limiting via sleep delays
- Graceful handling of missing Wikipedia results

---

*Testing analysis: 2026-01-25*
