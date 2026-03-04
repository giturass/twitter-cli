"""CLI entry point for twitter-cli.

Usage:
    twitter feed                      # full pipeline: fetch → filter → AI summarize
    twitter feed --count 50           # custom fetch count
    twitter feed --no-summary         # skip AI summary
    twitter feed --no-filter          # skip filtering
    twitter feed --json               # JSON output
    twitter feed --browser firefox    # specify browser for cookie extraction
    twitter bookmarks                 # fetch bookmarks
    twitter bookmarks --count 30
    twitter feed --input tweets.json  # summarize existing data
    twitter feed --output out.json    # save filtered tweets
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import List

import click
from rich.console import Console

from . import __version__
from .auth import get_cookies
from .client import TwitterClient
from .config import load_config
from .filter import filter_tweets
from .formatter import (
    print_filter_stats,
    print_tweet_table,
    tweets_to_json,
)
from .models import Author, Metrics, Tweet, TweetMedia
from .summarizer import summarize

console = Console()


def _setup_logging(verbose):
    # type: (bool) -> None
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _load_tweets_from_json(path):
    # type: (str) -> List[Tweet]
    """Load tweets from a JSON file (previously exported)."""
    raw = Path(path).read_text(encoding="utf-8")
    items = json.loads(raw)
    tweets = []
    for d in items:
        author_data = d.get("author", {})
        metrics_data = d.get("metrics", {})
        media_data = d.get("media", [])

        author = Author(
            id=author_data.get("id", ""),
            name=author_data.get("name", ""),
            screen_name=author_data.get("screenName", ""),
            profile_image_url=author_data.get("profileImageUrl", ""),
            verified=author_data.get("verified", False),
        )
        metrics = Metrics(
            likes=metrics_data.get("likes", 0),
            retweets=metrics_data.get("retweets", 0),
            replies=metrics_data.get("replies", 0),
            quotes=metrics_data.get("quotes", 0),
            views=metrics_data.get("views", 0),
            bookmarks=metrics_data.get("bookmarks", 0),
        )
        media = [
            TweetMedia(
                type=m.get("type", ""),
                url=m.get("url", ""),
                width=m.get("width"),
                height=m.get("height"),
            )
            for m in media_data
        ]

        qt_data = d.get("quotedTweet")
        quoted_tweet = None
        if qt_data:
            qt_author = qt_data.get("author", {})
            quoted_tweet = Tweet(
                id=qt_data.get("id", ""),
                text=qt_data.get("text", ""),
                author=Author(
                    id="",
                    name=qt_author.get("name", ""),
                    screen_name=qt_author.get("screenName", ""),
                ),
                metrics=Metrics(),
                created_at="",
            )

        tweets.append(Tweet(
            id=d.get("id", ""),
            text=d.get("text", ""),
            author=author,
            metrics=metrics,
            created_at=d.get("createdAt", ""),
            media=media,
            urls=d.get("urls", []),
            is_retweet=d.get("isRetweet", False),
            lang=d.get("lang", ""),
            retweeted_by=d.get("retweetedBy"),
            quoted_tweet=quoted_tweet,
            score=d.get("score", 0.0),
        ))
    return tweets


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
@click.version_option(version=__version__)
def cli(verbose):
    # type: (bool) -> None
    """twitter — Twitter/X CLI tool 🐦"""
    _setup_logging(verbose)


# ===== Feed =====

@cli.command()
@click.option("--count", "-n", type=int, default=None, help="Number of tweets to fetch.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option("--browser", "-b", default="chrome", help="Browser to extract cookies from.")
@click.option("--input", "-i", "input_file", type=str, default=None, help="Load tweets from JSON file.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Save filtered tweets to JSON file.")
@click.option("--no-filter", is_flag=True, help="Skip filtering.")
@click.option("--no-summary", is_flag=True, help="Skip AI summary.")
def feed(count, as_json, browser, input_file, output_file, no_filter, no_summary):
    # type: (int, bool, str, str, str, bool, bool) -> None
    """Fetch home timeline — full pipeline: fetch → filter → AI summarize."""
    config = load_config()

    # Step 1: Get tweets
    if input_file:
        console.print("📂 Loading tweets from %s..." % input_file)
        tweets = _load_tweets_from_json(input_file)
        console.print("   Loaded %d tweets" % len(tweets))
    else:
        fetch_count = count or config.get("fetch", {}).get("count", 50)
        console.print("\n🔐 Getting Twitter cookies...")
        try:
            cookies = get_cookies(browser)
        except RuntimeError as e:
            console.print("[red]❌ %s[/red]" % e)
            sys.exit(1)

        client = TwitterClient(cookies["auth_token"], cookies["ct0"])
        console.print("📡 Fetching home timeline (%d tweets)...\n" % fetch_count)
        start = time.time()
        tweets = client.fetch_home_timeline(fetch_count)
        elapsed = time.time() - start
        console.print("✅ Fetched %d tweets in %.1fs\n" % (len(tweets), elapsed))

    # Step 2: Filter
    if no_filter:
        filtered = tweets
    else:
        filter_config = config.get("filter", {})
        original_count = len(tweets)
        filtered = filter_tweets(tweets, filter_config)
        print_filter_stats(original_count, filtered, console)
        console.print()

    # Save filtered tweets
    if output_file:
        Path(output_file).write_text(tweets_to_json(filtered), encoding="utf-8")
        console.print("💾 Saved filtered tweets to %s\n" % output_file)

    # Output
    if as_json:
        click.echo(tweets_to_json(filtered))
        return

    print_tweet_table(filtered, console)
    console.print()

    # Step 3: AI Summary
    if no_summary:
        return

    ai_config = config.get("ai", {})
    if not ai_config.get("api_key"):
        console.print(
            "[yellow]⚠️  AI summary skipped: no API key configured.[/yellow]\n"
            "   Set ai.api_key in config.yaml or export AI_API_KEY=your_key"
        )
        return

    try:
        console.print("🤖 Calling AI (%s/%s)..." % (ai_config.get("provider", "openai"), ai_config.get("model", "")))
        summary = summarize(filtered, ai_config)
        console.print("\n" + "═" * 50)
        console.print("📝 AI Summary")
        console.print("═" * 50 + "\n")
        console.print(summary)
        console.print()
    except Exception as e:
        console.print("[red]❌ AI summary failed: %s[/red]" % e)


# ===== Bookmarks =====

@cli.command()
@click.option("--count", "-n", type=int, default=None, help="Number of tweets to fetch.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option("--browser", "-b", default="chrome", help="Browser to extract cookies from.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Save tweets to JSON file.")
@click.option("--no-filter", is_flag=True, help="Skip filtering.")
@click.option("--no-summary", is_flag=True, help="Skip AI summary.")
def bookmarks(count, as_json, browser, output_file, no_filter, no_summary):
    # type: (int, bool, str, str, bool, bool) -> None
    """Fetch bookmarked tweets."""
    config = load_config()
    fetch_count = count or 50

    console.print("\n🔐 Getting Twitter cookies...")
    try:
        cookies = get_cookies(browser)
    except RuntimeError as e:
        console.print("[red]❌ %s[/red]" % e)
        sys.exit(1)

    client = TwitterClient(cookies["auth_token"], cookies["ct0"])
    console.print("🔖 Fetching bookmarks (%d tweets)...\n" % fetch_count)
    start = time.time()
    tweets = client.fetch_bookmarks(fetch_count)
    elapsed = time.time() - start
    console.print("✅ Fetched %d bookmarks in %.1fs\n" % (len(tweets), elapsed))

    # Filter
    if no_filter:
        filtered = tweets
    else:
        filter_config = config.get("filter", {})
        original_count = len(tweets)
        filtered = filter_tweets(tweets, filter_config)
        print_filter_stats(original_count, filtered, console)
        console.print()

    # Save
    if output_file:
        Path(output_file).write_text(tweets_to_json(filtered), encoding="utf-8")
        console.print("💾 Saved to %s\n" % output_file)

    # Output
    if as_json:
        click.echo(tweets_to_json(filtered))
        return

    print_tweet_table(filtered, console, title="🔖 Bookmarks — %d tweets" % len(filtered))
    console.print()

    # AI Summary
    if no_summary:
        return

    ai_config = config.get("ai", {})
    if not ai_config.get("api_key"):
        console.print(
            "[yellow]⚠️  AI summary skipped: no API key configured.[/yellow]"
        )
        return

    try:
        console.print("🤖 Calling AI...")
        summary = summarize(filtered, ai_config)
        console.print("\n" + "═" * 50)
        console.print("📝 AI Summary")
        console.print("═" * 50 + "\n")
        console.print(summary)
    except Exception as e:
        console.print("[red]❌ AI summary failed: %s[/red]" % e)


if __name__ == "__main__":
    cli()
