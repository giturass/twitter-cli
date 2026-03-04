"""Cookie authentication for Twitter/X.

Supports:
1. Environment variables: TWITTER_AUTH_TOKEN + TWITTER_CT0
2. Auto-extract from browser via browser-cookie3 (subprocess)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Dict, Optional


def load_from_env() -> Optional[Dict[str, str]]:
    """Load cookies from environment variables."""
    auth_token = os.environ.get("TWITTER_AUTH_TOKEN", "")
    ct0 = os.environ.get("TWITTER_CT0", "")
    if auth_token and ct0:
        return {"auth_token": auth_token, "ct0": ct0}
    return None


def extract_from_browser(browser: str = "chrome") -> Optional[Dict[str, str]]:
    """Auto-extract cookies from local browser using browser-cookie3.

    Runs in a subprocess to avoid SQLite database lock issues when the
    browser is running.
    """
    extract_script = '''
import json, sys
try:
    import browser_cookie3
except ImportError:
    print(json.dumps({"error": "browser-cookie3 not installed"}))
    sys.exit(1)

browser_funcs = {
    "chrome": browser_cookie3.chrome,
    "firefox": browser_cookie3.firefox,
    "edge": browser_cookie3.edge,
    "brave": browser_cookie3.brave,
}

browser_name = "%s"
fn = browser_funcs.get(browser_name)
if not fn:
    print(json.dumps({"error": "Unsupported browser: " + browser_name}))
    sys.exit(1)

try:
    jar = fn()
except Exception as e:
    print(json.dumps({"error": str(e)}))
    sys.exit(1)

result = {}
for cookie in jar:
    domain = cookie.domain or ""
    if domain.endswith(".x.com") or domain.endswith(".twitter.com") or domain in ("x.com", "twitter.com", ".x.com", ".twitter.com"):
        if cookie.name == "auth_token":
            result["auth_token"] = cookie.value
        elif cookie.name == "ct0":
            result["ct0"] = cookie.value

if "auth_token" in result and "ct0" in result:
    print(json.dumps(result))
else:
    print(json.dumps({"error": "Could not find auth_token and ct0 cookies. Make sure you are logged into x.com in " + browser_name + "."}))
    sys.exit(1)
''' % browser

    try:
        result = subprocess.run(
            [sys.executable, "-c", extract_script],
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = result.stdout.strip()
        if not output:
            stderr = result.stderr.strip()
            if stderr:
                # Maybe browser-cookie3 not installed, try with uv
                result2 = subprocess.run(
                    ["uv", "run", "--with", "browser-cookie3", "python3", "-c", extract_script],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                output = result2.stdout.strip()
                if not output:
                    return None

        data = json.loads(output)
        if "error" in data:
            return None
        return {"auth_token": data["auth_token"], "ct0": data["ct0"]}
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, FileNotFoundError):
        return None


def get_cookies(browser: str = "chrome") -> Dict[str, str]:
    """Get Twitter cookies. Priority: env vars -> browser extraction.

    Returns dict with 'auth_token' and 'ct0' keys.
    Raises RuntimeError if no cookies found.
    """
    # 1. Try environment variables
    env_cookies = load_from_env()
    if env_cookies:
        return env_cookies

    # 2. Try browser extraction
    browser_cookies = extract_from_browser(browser)
    if browser_cookies:
        return browser_cookies

    raise RuntimeError(
        "No Twitter cookies found.\n"
        "Option 1: Set TWITTER_AUTH_TOKEN and TWITTER_CT0 environment variables\n"
        "Option 2: Make sure you are logged into x.com in your browser"
    )
