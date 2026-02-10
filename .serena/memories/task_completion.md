# Task Completion Checklist

## Before Committing Changes
1. Run syntax check on modified files:
   ```bash
   python -m py_compile <modified_file.py>
   ```

2. Verify CLI still works:
   ```bash
   python broll.py pipeline --help
   ```

3. If modifying tools, test they run standalone:
   ```bash
   python tools/<tool_name>.py --help
   ```

## Common Issues
- **Config import fails**: Ensure `sys.path.insert` is before `import config`
- **API errors**: Check `.wikipedia_image_downloader.ini` has valid keys
- **Pipeline fails mid-run**: Use `--resume` to continue from checkpoint
