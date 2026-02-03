"""
Shared configuration loading for b-roll-finder-app.

Loads API keys and settings from INI config files and sets them as environment
variables so they're available throughout the application.

Config file locations (first found wins):
  - ./.wikipedia_image_downloader.ini
  - ~/.wikipedia_image_downloader.ini
  - ~/.config/wikipedia_image_downloader/config.ini

INI format:
  [settings]
  output_dir = /path/to/output
  ANTHROPIC_API_KEY = sk-ant-...
  OPENAI_API_KEY = sk-proj-...
  WIKIPEDIA_API_ACCESS_TOKEN = eyJ...
"""

import configparser
import os
import re
from pathlib import Path
from typing import Optional, List

# Keys that should be loaded as environment variables
# Pattern: uppercase letters, digits, underscores - typically ending in _KEY, _TOKEN, _SECRET, _ID
ENV_VAR_PATTERN = re.compile(r'^[A-Z][A-Z0-9_]*(?:_KEY|_TOKEN|_SECRET|_ID)$')

# Explicit list of known API keys to load (in case pattern doesn't match)
KNOWN_API_KEYS = [
    'ANTHROPIC_API_KEY',
    'OPENAI_API_KEY',
    'OPENAI_API_BASE',
    'WIKIPEDIA_API_CLIENT_ID',
    'WIKIPEDIA_API_CLIENT_SECRET',
    'WIKIPEDIA_API_ACCESS_TOKEN',
    'WIKI_IMG_OUTPUT_DIR',
]


def get_config_paths() -> List[Path]:
    """Return list of config file paths to check, in priority order."""
    return [
        Path.cwd() / ".wikipedia_image_downloader.ini",
        Path.home() / ".wikipedia_image_downloader.ini",
        Path.home() / ".config" / "wikipedia_image_downloader" / "config.ini",
    ]


def load_config() -> Optional[Path]:
    """
    Load configuration from INI file and set API keys as environment variables.

    Only sets environment variables if they're not already set, so explicit
    env vars take precedence over config file values.

    Returns the path to the config file that was loaded, or None if no config found.
    """
    candidates = get_config_paths()
    parser = configparser.ConfigParser()

    for cfg_path in candidates:
        try:
            if not cfg_path.exists():
                continue

            parser.read(cfg_path)

            if not parser.has_section("settings"):
                continue

            # Load all settings that look like API keys
            for key, value in parser.items("settings"):
                key_upper = key.upper()
                value = value.strip()

                if not value:
                    continue

                # Check if this is a known API key or matches the pattern
                is_api_key = (
                    key_upper in KNOWN_API_KEYS or
                    ENV_VAR_PATTERN.match(key_upper)
                )

                if is_api_key:
                    # Only set if not already in environment
                    if key_upper not in os.environ:
                        os.environ[key_upper] = value

            return cfg_path

        except Exception:
            # Ignore malformed configs and try next
            continue

    return None


def get_output_dir() -> Optional[str]:
    """
    Get output_dir from config file.

    Note: This is a convenience function. Most scripts should use their own
    resolution logic that considers CLI args and env vars first.
    """
    candidates = get_config_paths()
    parser = configparser.ConfigParser()

    for cfg_path in candidates:
        try:
            if not cfg_path.exists():
                continue
            parser.read(cfg_path)
            if parser.has_section("settings"):
                out = parser.get("settings", "output_dir", fallback="").strip()
                if out:
                    return out
        except Exception:
            continue

    return None


# Auto-load config when module is imported
_config_path = load_config()
