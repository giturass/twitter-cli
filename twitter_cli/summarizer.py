"""AI summarization module.

Supports OpenAI-compatible (doubao, deepseek, openai) and Anthropic APIs.
Uses urllib.request for zero extra dependencies.
"""

from __future__ import annotations

import json
import logging
import ssl
import urllib.request
from typing import Any, Dict, List

from .models import Tweet

logger = logging.getLogger(__name__)

SYSTEM_MESSAGE = "你是一个专业的 Twitter/X 信息流分析师，擅长提炼关键信息和发现趋势。"


def _build_prompt(tweets, language="zh-CN"):
    # type: (List[Tweet], str) -> str
    """Build the summarization prompt."""
    lines = []
    for i, t in enumerate(tweets):
        score_str = " [score: %.1f]" % t.score if t.score else ""
        rt = " (RT by @%s)" % t.retweeted_by if t.is_retweet and t.retweeted_by else ""
        media_str = ""
        if t.media:
            media_str = " [%s]" % ", ".join(m.type for m in t.media)
        url_str = ""
        if t.urls:
            url_str = "\n   Links: %s" % ", ".join(t.urls)
        quoted = ""
        if t.quoted_tweet:
            qt = t.quoted_tweet
            quoted = "\n   Quoting @%s: %s..." % (qt.author.screen_name, qt.text[:100].replace("\n", " "))

        text_preview = t.text.replace("\n", " ")[:300]
        lines.append(
            '%d. @%s (%s)%s%s\n'
            '   "%s"\n'
            '   ❤️%d 🔄%d 💬%d 🔖%d 👁️%d%s%s%s'
            % (
                i + 1, t.author.screen_name, t.author.name, rt, score_str,
                text_preview,
                t.metrics.likes, t.metrics.retweets, t.metrics.replies,
                t.metrics.bookmarks, t.metrics.views,
                media_str, url_str, quoted,
            )
        )

    tweet_summaries = "\n\n".join(lines)

    if language.startswith("zh"):
        lang_inst = "请用中文输出。"
    else:
        lang_inst = "Please output in %s." % language

    return (
        "你是一个 Twitter/X 信息流分析师。请对以下 %d 条推文进行摘要总结。\n\n"
        "要求：\n"
        "1. 按主题分组（如：AI & 编程、Crypto、工具推荐、生活观点等）\n"
        "2. 每组列出关键推文和核心观点，标注作者 @handle\n"
        "3. 标注数据亮点（高赞/高收藏推文用 🔥 标记）\n"
        "4. 最后用 2-3 句话总结今天 timeline 的整体趋势\n"
        "5. %s\n\n"
        "推文数据：\n\n%s"
    ) % (len(tweets), lang_inst, tweet_summaries)


def _call_openai(prompt, config):
    # type: (str, Dict[str, Any]) -> str
    """Call OpenAI-compatible API."""
    url = config.get("base_url", "").rstrip("/")
    if not url.endswith("/chat/completions"):
        if not url.endswith("/v1"):
            url += "/v1"
        url += "/chat/completions"

    payload = json.dumps({
        "model": config.get("model", ""),
        "messages": [
            {"role": "system", "content": SYSTEM_MESSAGE},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 4096,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer %s" % config.get("api_key", ""))

    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    choices = data.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("content", "")
    return ""


def _call_anthropic(prompt, config):
    # type: (str, Dict[str, Any]) -> str
    """Call Anthropic Messages API."""
    url = config.get("base_url", "").rstrip("/")
    if not url.endswith("/messages"):
        if not url.endswith("/v1"):
            url += "/v1"
        url += "/messages"

    payload = json.dumps({
        "model": config.get("model", ""),
        "system": SYSTEM_MESSAGE,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 4096,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload)
    req.add_header("Content-Type", "application/json")
    req.add_header("x-api-key", config.get("api_key", ""))
    req.add_header("anthropic-version", "2023-06-01")

    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    content_blocks = data.get("content", [])
    for block in content_blocks:
        if block.get("type") == "text":
            return block.get("text", "")
    return ""


def summarize(tweets, config):
    # type: (List[Tweet], Dict[str, Any]) -> str
    """Summarize tweets using the configured AI provider.

    Config keys: provider, api_key, model, base_url, language
    """
    api_key = config.get("api_key", "")
    if not api_key:
        raise RuntimeError(
            "AI API key not configured.\n"
            "Set ai.api_key in config.yaml or export AI_API_KEY=your_key"
        )

    if not tweets:
        return "No tweets to summarize."

    language = config.get("language", "zh-CN")
    prompt = _build_prompt(tweets, language)
    provider = config.get("provider", "openai")

    logger.info("Calling AI (%s/%s)...", provider, config.get("model", ""))

    if provider == "anthropic":
        return _call_anthropic(prompt, config)
    else:
        return _call_openai(prompt, config)
