"""Configuration loader — reads config.yaml and merges with defaults.

Uses a simple built-in YAML parser to avoid adding PyYAML as a dependency.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Union

# Default configuration
DEFAULT_CONFIG = {
    "fetch": {
        "count": 50,
    },
    "filter": {
        "mode": "topN",
        "topN": 20,
        "minScore": 50,
        "lang": [],
        "excludeRetweets": False,
        "weights": {
            "likes": 1.0,
            "retweets": 3.0,
            "replies": 2.0,
            "bookmarks": 5.0,
            "views_log": 0.5,
        },
    },
    "ai": {
        "provider": "openai",
        "api_key": "",
        "model": "doubao-seed-2.0-code",
        "base_url": "https://ark.cn-beijing.volces.com/api/coding",
        "language": "zh-CN",
    },
}  # type: Dict[str, Any]


def _parse_value(s):
    # type: (str) -> Union[str, int, float, bool]
    """Parse a scalar YAML value."""
    if s == "true":
        return True
    if s == "false":
        return False
    # Remove surrounding quotes
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    # Try number
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return s


def _parse_yaml(text):
    # type: (str) -> Dict[str, Any]
    """Minimal YAML parser for our flat config structure.

    Supports: scalars, inline arrays [...], indented "- item" arrays,
    nested objects via indentation.
    """
    result = {}  # type: Dict[str, Any]
    lines = text.split("\n")
    stack = [{"indent": -1, "obj": result}]  # type: List[Dict[str, Any]]

    for line in lines:
        # Strip comments and trailing whitespace
        trimmed = re.sub(r"#.*$", "", line).rstrip()
        if not trimmed or not trimmed.strip():
            continue

        indent = len(line) - len(line.lstrip())
        content = trimmed.strip()

        # Handle "- item" array entries
        if content.startswith("- "):
            parent = stack[-1]["obj"]
            keys = list(parent.keys())
            if keys:
                last_key = keys[-1]
                if not isinstance(parent[last_key], list):
                    parent[last_key] = []
                parent[last_key].append(_parse_value(content[2:].strip()))
            continue

        colon_idx = content.find(":")
        if colon_idx == -1:
            continue

        key = content[:colon_idx].strip()
        raw_value = content[colon_idx + 1:].strip()

        # Pop stack to find parent at correct indentation
        while len(stack) > 1 and stack[-1]["indent"] >= indent:
            stack.pop()
        parent = stack[-1]["obj"]

        if raw_value == "" or raw_value == "|":
            # Nested object
            child = {}  # type: Dict[str, Any]
            parent[key] = child
            stack.append({"indent": indent, "obj": child})
        elif raw_value.startswith("[") and raw_value.endswith("]"):
            # Inline array
            inner = raw_value[1:-1].strip()
            if inner == "":
                parent[key] = []
            else:
                parent[key] = [_parse_value(s.strip()) for s in inner.split(",")]
        else:
            parent[key] = _parse_value(raw_value)

    return result


def _deep_merge(target, source):
    # type: (Dict[str, Any], Dict[str, Any]) -> Dict[str, Any]
    """Deep merge source into target (source values override target)."""
    result = dict(target)
    for key in source:
        if (
            isinstance(source[key], dict)
            and isinstance(result.get(key), dict)
        ):
            result[key] = _deep_merge(result[key], source[key])
        else:
            result[key] = source[key]
    return result


def load_config(config_path=None):
    # type: (str) -> Dict[str, Any]
    """Load config from config.yaml, merged with defaults."""
    if config_path is None:
        # Look in current directory first, then script directory
        candidates = [
            Path.cwd() / "config.yaml",
            Path(__file__).parent.parent / "config.yaml",
        ]
        for p in candidates:
            if p.exists():
                config_path = str(p)
                break

    if config_path and Path(config_path).exists():
        try:
            raw = Path(config_path).read_text(encoding="utf-8")
            parsed = _parse_yaml(raw)
            config = _deep_merge(DEFAULT_CONFIG, parsed)
        except Exception:
            config = dict(DEFAULT_CONFIG)
    else:
        config = dict(DEFAULT_CONFIG)

    # Ensure nested dicts exist
    config.setdefault("fetch", DEFAULT_CONFIG["fetch"])
    config.setdefault("filter", DEFAULT_CONFIG["filter"])
    config.setdefault("ai", DEFAULT_CONFIG["ai"])

    # Deep-copy filter weights if needed
    if "filter" in config and "weights" not in config["filter"]:
        config["filter"]["weights"] = dict(DEFAULT_CONFIG["filter"]["weights"])

    # AI API key fallback to env var
    ai = config.get("ai", {})
    if not ai.get("api_key"):
        ai["api_key"] = os.environ.get("AI_API_KEY", "")

    return config
