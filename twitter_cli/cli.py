"""CLI entry point for twitter-cli.

Usage:
    twitter feed                      # fetch home timeline → filter
    twitter feed --max 50             # custom fetch count
    twitter feed --no-filter          # skip filtering
    twitter feed --json               # JSON output
    twitter favorite                  # fetch bookmarks
    twitter favorite --max 30
    twitter feed --input tweets.json  # load existing data
    twitter feed --output out.json    # save filtered tweets
    twitter post "Hello"              # post a tweet
    twitter reply ID "text"           # reply to a tweet
    twitter quote ID "text"           # quote a tweet
    twitter delete ID                 # delete a tweet
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
    print_user_profile,
    print_user_table,
    tweets_to_json,
)
from .models import Author, Metrics, Tweet, TweetMedia


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
@click.option("--max", "-n", "max_count", type=int, default=None, help="Max number of tweets to fetch.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option("--input", "-i", "input_file", type=str, default=None, help="Load tweets from JSON file.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Save filtered tweets to JSON file.")
@click.option("--no-filter", is_flag=True, help="Skip filtering.")
def feed(max_count, as_json, input_file, output_file, no_filter):
    # type: (int, bool, str, str, bool) -> None
    """Fetch home timeline with filtering."""
    config = load_config()

    # Step 1: Get tweets
    if input_file:
        console.print("📂 Loading tweets from %s..." % input_file)
        tweets = _load_tweets_from_json(input_file)
        console.print("   Loaded %d tweets" % len(tweets))
    else:
        fetch_count = max_count or config.get("fetch", {}).get("count", 50)
        console.print("\n🔐 Getting Twitter cookies...")
        try:
            cookies = get_cookies()
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


# ===== Favorite =====

@cli.command()
@click.option("--max", "-n", "max_count", type=int, default=None, help="Max number of tweets to fetch.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option("--output", "-o", "output_file", type=str, default=None, help="Save tweets to JSON file.")
@click.option("--no-filter", is_flag=True, help="Skip filtering.")
def favorite(max_count, as_json, output_file, no_filter):
    # type: (int, bool, str, bool) -> None
    """Fetch bookmarked (favorite) tweets."""
    config = load_config()
    fetch_count = max_count or 50

    console.print("\n🔐 Getting Twitter cookies...")
    try:
        cookies = get_cookies()
    except RuntimeError as e:
        console.print("[red]❌ %s[/red]" % e)
        sys.exit(1)

    client = TwitterClient(cookies["auth_token"], cookies["ct0"])
    console.print("🔖 Fetching favorites (%d tweets)...\n" % fetch_count)
    start = time.time()
    tweets = client.fetch_bookmarks(fetch_count)
    elapsed = time.time() - start
    console.print("✅ Fetched %d favorites in %.1fs\n" % (len(tweets), elapsed))

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

    print_tweet_table(filtered, console, title="🔖 Favorites — %d tweets" % len(filtered))
    console.print()


# ===== User =====

@cli.command()
@click.argument("screen_name")
def user(screen_name):
    # type: (str,) -> None
    """View a user's profile. SCREEN_NAME is the @handle (without @)."""
    screen_name = screen_name.lstrip("@")
    client = _get_client()
    console.print("👤 Fetching user @%s..." % screen_name)
    try:
        profile = client.fetch_user(screen_name)
        console.print()
        print_user_profile(profile, console)
    except RuntimeError as e:
        console.print("[red]❌ %s[/red]" % e)
        sys.exit(1)


@cli.command("user-posts")
@click.argument("screen_name")
@click.option("--max", "-n", "max_count", type=int, default=20, help="Max number of tweets to fetch.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def user_posts(screen_name, max_count, as_json):
    # type: (str, int, bool) -> None
    """List a user's tweets. SCREEN_NAME is the @handle (without @)."""
    screen_name = screen_name.lstrip("@")
    client = _get_client()
    console.print("👤 Fetching @%s's profile..." % screen_name)
    try:
        profile = client.fetch_user(screen_name)
    except RuntimeError as e:
        console.print("[red]❌ %s[/red]" % e)
        sys.exit(1)

    console.print("📝 Fetching tweets (%d)...\n" % max_count)
    start = time.time()
    try:
        tweets = client.fetch_user_tweets(profile.id, max_count)
    except RuntimeError as e:
        console.print("[red]❌ %s[/red]" % e)
        sys.exit(1)
    elapsed = time.time() - start
    console.print("✅ Fetched %d tweets in %.1fs\n" % (len(tweets), elapsed))

    if as_json:
        click.echo(tweets_to_json(tweets))
        return

    print_tweet_table(tweets, console, title="📝 @%s — %d tweets" % (screen_name, len(tweets)))
    console.print()


@cli.command()
@click.argument("screen_name")
@click.option("--max", "-n", "max_count", type=int, default=20, help="Max number of users to show.")
def followers(screen_name, max_count):
    # type: (str, int) -> None
    """List a user's followers. SCREEN_NAME is the @handle (without @)."""
    screen_name = screen_name.lstrip("@")
    client = _get_client()
    console.print("👤 Fetching @%s's profile..." % screen_name)
    try:
        profile = client.fetch_user(screen_name)
    except RuntimeError as e:
        console.print("[red]❌ %s[/red]" % e)
        sys.exit(1)

    console.print("👥 Fetching followers...\n")
    try:
        users = client.fetch_followers(profile.id, max_count)
    except RuntimeError as e:
        console.print("[red]❌ %s[/red]" % e)
        sys.exit(1)
    print_user_table(users, console, title="👥 @%s's followers — %d" % (screen_name, len(users)))
    console.print()


@cli.command()
@click.argument("screen_name")
@click.option("--max", "-n", "max_count", type=int, default=20, help="Max number of users to show.")
def following(screen_name, max_count):
    # type: (str, int) -> None
    """List users that someone follows. SCREEN_NAME is the @handle (without @)."""
    screen_name = screen_name.lstrip("@")
    client = _get_client()
    console.print("👤 Fetching @%s's profile..." % screen_name)
    try:
        profile = client.fetch_user(screen_name)
    except RuntimeError as e:
        console.print("[red]❌ %s[/red]" % e)
        sys.exit(1)

    console.print("👥 Fetching following...\n")
    try:
        users = client.fetch_following(profile.id, max_count)
    except RuntimeError as e:
        console.print("[red]❌ %s[/red]" % e)
        sys.exit(1)
    print_user_table(users, console, title="👥 @%s follows — %d" % (screen_name, len(users)))
    console.print()


# ===== Post / Reply / Quote / Delete =====

def _get_client():
    # type: () -> TwitterClient
    """Helper to authenticate and create a TwitterClient."""
    console.print("\n🔐 Getting Twitter cookies...")
    try:
        cookies = get_cookies()
    except RuntimeError as e:
        console.print("[red]❌ %s[/red]" % e)
        sys.exit(1)
    return TwitterClient(cookies["auth_token"], cookies["ct0"])


@cli.command()
@click.argument("text")
def post(text):
    # type: (str,) -> None
    """Post a new tweet."""
    client = _get_client()
    console.print("✏️  Posting tweet...")
    try:
        result = client.create_tweet(text)
        tweet_id = result["tweet_id"]
        console.print("\n[green]✅ Tweet posted![/green]")
        console.print("   ID: %s" % tweet_id)
        console.print("   URL: https://x.com/i/status/%s" % tweet_id)
        console.print('   Text: "%s"' % result["text"][:100])
    except RuntimeError as e:
        console.print("[red]❌ %s[/red]" % e)
        sys.exit(1)


@cli.command()
@click.argument("tweet_id")
@click.argument("text")
def reply(tweet_id, text):
    # type: (str, str) -> None
    """Reply to a tweet."""
    client = _get_client()
    console.print("💬 Replying to %s..." % tweet_id)
    try:
        result = client.create_tweet(text, reply_to=tweet_id)
        new_id = result["tweet_id"]
        console.print("\n[green]✅ Reply posted![/green]")
        console.print("   ID: %s" % new_id)
        console.print("   URL: https://x.com/i/status/%s" % new_id)
        console.print('   Text: "%s"' % result["text"][:100])
    except RuntimeError as e:
        console.print("[red]❌ %s[/red]" % e)
        sys.exit(1)


@cli.command()
@click.argument("tweet_url")
@click.argument("text")
def quote(tweet_url, text):
    # type: (str, str) -> None
    """Quote a tweet. TWEET_URL can be a full URL or tweet ID."""
    # If user passes just an ID, convert to URL
    if not tweet_url.startswith("http"):
        tweet_url = "https://x.com/i/status/%s" % tweet_url
    client = _get_client()
    console.print("🔄 Quoting %s..." % tweet_url)
    try:
        result = client.create_tweet(text, quote_tweet_url=tweet_url)
        new_id = result["tweet_id"]
        console.print("\n[green]✅ Quote tweet posted![/green]")
        console.print("   ID: %s" % new_id)
        console.print("   URL: https://x.com/i/status/%s" % new_id)
        console.print('   Text: "%s"' % result["text"][:100])
    except RuntimeError as e:
        console.print("[red]❌ %s[/red]" % e)
        sys.exit(1)


@cli.command()
@click.argument("tweet_id")
@click.confirmation_option(prompt="Are you sure you want to delete this tweet?")
def delete(tweet_id):
    # type: (str,) -> None
    """Delete a tweet by ID."""
    client = _get_client()
    console.print("🗑️  Deleting tweet %s..." % tweet_id)
    try:
        client.delete_tweet(tweet_id)
        console.print("\n[green]✅ Tweet deleted![/green]")
        console.print("   ID: %s" % tweet_id)
    except RuntimeError as e:
        console.print("[red]❌ %s[/red]" % e)
        sys.exit(1)


if __name__ == "__main__":
    cli()
