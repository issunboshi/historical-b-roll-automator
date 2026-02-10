#!/usr/bin/env python3
"""Export OpenAPI specification to file."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Export OpenAPI specification")
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=Path("openapi.json"),
        help="Output file path (default: openapi.json)",
    )
    parser.add_argument(
        "--yaml",
        action="store_true",
        help="Export as YAML instead of JSON",
    )
    args = parser.parse_args()

    # Import app to get schema
    from src.api.main import create_app

    app = create_app()
    schema = app.openapi()

    if args.yaml:
        try:
            import yaml
            content = yaml.dump(schema, default_flow_style=False, sort_keys=False)
        except ImportError:
            print("PyYAML not installed. Use --output with .json or install pyyaml.", file=sys.stderr)
            sys.exit(1)
    else:
        content = json.dumps(schema, indent=2)

    args.output.write_text(content)
    print(f"OpenAPI spec written to: {args.output}")


if __name__ == "__main__":
    main()
