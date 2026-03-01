# `--retry-failed` Download Flag — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `--retry-failed` flag to the download command that retries only entities with `download_status == "failed"` or `"no_images"`.

**Architecture:** Flag on `download_entities.py` changes entity filter from "no images" to "download_status=failed", clears stale state, and passes `force=True` to `download_entity()` to bypass the directory-exists skip gate. `broll.py` forwards the flag via subprocess.

**Tech Stack:** Python argparse, existing download pipeline

---

### Task 1: Add `force` parameter to `download_entity()`

**Files:**
- Modify: `tools/download_entities.py:319` (function signature)
- Modify: `tools/download_entities.py:422-427` (skip gate)

**Step 1: Add `force` param after `thumbnail_width`**

In `tools/download_entities.py`, the function signature at line 319:

```python
    thumbnail_width: int = 0,
    force: bool = False,
) -> Tuple[str, bool, Path, Optional[str], Optional[dict]]:
```

**Step 2: Bypass skip gate when `force=True`**

At line 422-427, change:

```python
    # If the entity output directory already exists, skip the download step
    if entity_dir.exists():
        safe_print(f"[{current_idx}/{total_entities}] Skipping: {entity_name} (already downloaded)")
        return (entity_name, True, entity_dir, entity_name, disambiguation_result)
```

To:

```python
    # If the entity output directory already exists, skip the download step
    if entity_dir.exists() and not force:
        safe_print(f"[{current_idx}/{total_entities}] Skipping: {entity_name} (already downloaded)")
        return (entity_name, True, entity_dir, entity_name, disambiguation_result)
```

**Step 3: Verify syntax**

Run: `python -m py_compile tools/download_entities.py`

**Step 4: Commit**

```bash
git add tools/download_entities.py
git commit -m "feat(download): add force param to download_entity() to bypass dir-exists skip"
```

---

### Task 2: Add `--retry-failed` argparse and filter logic to `download_entities.py`

**Files:**
- Modify: `tools/download_entities.py:637` (argparse, after `--interactive`)
- Modify: `tools/download_entities.py:708-716` (entity filter)
- Modify: `tools/download_entities.py:841,892` (call sites — pass `force`)

**Step 1: Add argparse flag**

After the `--interactive` argument (line 637), add:

```python
    parser.add_argument("--retry-failed", action="store_true",
                        help="Retry only entities with download_status='failed' from a previous run")
```

**Step 2: Change entity filter logic**

Replace lines 708-716:

```python
    # Filter to entities that need downloading (don't already have images)
    need_download = [
        (name, payload) for name, payload in entities.items()
        if not payload.get("images")
    ]

    if not need_download:
        print("All entities already have images. Nothing to download.")
        return 0
```

With:

```python
    # Filter to entities that need downloading
    if getattr(args, 'retry_failed', False):
        need_download = [
            (name, payload) for name, payload in entities.items()
            if payload.get("download_status") == "failed"
        ]
        if not need_download:
            print("No entities with download_status='failed'. Nothing to retry.")
            return 0
        # Clear stale state so download + harvest work cleanly
        for name, payload in need_download:
            payload.pop("images", None)
            payload.pop("download_status", None)
        print(f"Retrying {len(need_download)} previously failed entities...")
    else:
        need_download = [
            (name, payload) for name, payload in entities.items()
            if not payload.get("images")
        ]
        if not need_download:
            print("All entities already have images. Nothing to download.")
            return 0
```

**Step 3: Pass `force` at both call sites**

At the sequential call site (~line 841), add after `thumbnail_width=`:

```python
                thumbnail_width=getattr(args, 'thumbnail_width', 0),
                force=getattr(args, 'retry_failed', False),
```

At the parallel call site (~line 892), add after `thumbnail_width=`:

```python
                    thumbnail_width=getattr(args, 'thumbnail_width', 0),
                    force=getattr(args, 'retry_failed', False),
```

**Step 4: Verify syntax**

Run: `python -m py_compile tools/download_entities.py`

**Step 5: Commit**

```bash
git add tools/download_entities.py
git commit -m "feat(download): add --retry-failed flag to download_entities.py"
```

---

### Task 3: Add `--retry-failed` to `broll.py` download subcommand

**Files:**
- Modify: `broll.py:1473` (p_download argparse, after `--interactive`)
- Modify: `broll.py:410-412` (cmd_download forwarding)

**Step 1: Add argparse flag to `p_download`**

After the `--interactive` argument on `p_download` (~line 1473), add:

```python
    p_download.add_argument("--retry-failed", action="store_true",
                            help="Retry only entities with download_status='failed' from a previous run")
```

**Step 2: Forward flag in `cmd_download()`**

After the thumbnail_width forwarding block (~line 412), add:

```python
    if getattr(args, 'retry_failed', False):
        cmd.append("--retry-failed")
```

**Step 3: Verify**

Run: `python -m py_compile broll.py`
Run: `python broll.py download --help` — verify `--retry-failed` appears

**Step 4: Commit**

```bash
git add broll.py
git commit -m "feat(download): forward --retry-failed from broll.py to download_entities.py"
```

---

### Task 4: Update docs

**Files:**
- Modify: `README.md` (download subcommand table)
- Modify: `CLAUDE.md` (download pipeline section)

**Step 1: Add to README download subcommand table**

In the `#### download` table, after `--thumbnail-width`, add:

```
| `--retry-failed` | Retry only entities that failed in a previous run |
```

**Step 2: Add to CLAUDE.md Download Pipeline section**

In `## Download Pipeline`, add:

```
- `--retry-failed` flag selects entities with `download_status == "failed"`, clears stale state, and bypasses the directory-exists skip gate
```

**Step 3: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: document --retry-failed flag"
```

---

### Task 5: Final verification

Run: `python -m py_compile tools/download_entities.py && python -m py_compile broll.py`
Run: `python broll.py download --help` — verify `--retry-failed` appears
Run: `python tools/download_entities.py --help` — verify `--retry-failed` appears
