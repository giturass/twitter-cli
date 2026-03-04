"""Tweet formatter for terminal output (rich) and JSON export."""

from __future__ import annotations

import json
from typing import List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .models import Tweet


def format_number(n):
    # type: (int) -> str
    """Format number with K/M suffixes."""
    if n >= 1_000_000:
        return "%.1fM" % (n / 1_000_000)
    if n >= 1_000:
        return "%.1fK" % (n / 1_000)
    return str(n)


def print_tweet_table(tweets, console=None, title=None):
    # type: (List[Tweet], Optional[Console], Optional[str]) -> None
    """Print tweets as a rich table."""
    if console is None:
        console = Console()

    if not title:
        title = "📱 Twitter — %d tweets" % len(tweets)

    table = Table(title=title, show_lines=True, expand=True)
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Author", style="cyan", width=18, no_wrap=True)
    table.add_column("Tweet", ratio=3)
    table.add_column("Stats", style="green", width=22, no_wrap=True)
    table.add_column("Score", style="yellow", width=6, justify="right")

    for i, tweet in enumerate(tweets):
        # Author
        verified = " ✓" if tweet.author.verified else ""
        author_text = "@%s%s" % (tweet.author.screen_name, verified)
        if tweet.is_retweet and tweet.retweeted_by:
            author_text += "\n🔄 @%s" % tweet.retweeted_by

        # Tweet text (truncated)
        text = tweet.text.replace("\n", " ").strip()
        if len(text) > 120:
            text = text[:117] + "..."

        # Media indicators
        if tweet.media:
            media_icons = []
            for m in tweet.media:
                if m.type == "photo":
                    media_icons.append("📷")
                elif m.type == "video":
                    media_icons.append("📹")
                else:
                    media_icons.append("🎞️")
            text += " " + " ".join(media_icons)

        # Quoted tweet
        if tweet.quoted_tweet:
            qt = tweet.quoted_tweet
            qt_text = qt.text.replace("\n", " ")[:60]
            text += "\n┌ @%s: %s" % (qt.author.screen_name, qt_text)

        # Stats
        stats = (
            "❤️ %s  🔄 %s\n💬 %s  👁️ %s"
            % (
                format_number(tweet.metrics.likes),
                format_number(tweet.metrics.retweets),
                format_number(tweet.metrics.replies),
                format_number(tweet.metrics.views),
            )
        )

        # Score
        score_str = "%.1f" % tweet.score if tweet.score else "-"

        table.add_row(str(i + 1), author_text, text, stats, score_str)

    console.print(table)


def print_tweet_detail(tweet, console=None):
    # type: (Tweet, Optional[Console]) -> None
    """Print a single tweet in detail using a rich panel."""
    if console is None:
        console = Console()

    verified = " ✓" if tweet.author.verified else ""
    header = "@%s%s (%s)" % (tweet.author.screen_name, verified, tweet.author.name)

    body_parts = []

    if tweet.is_retweet and tweet.retweeted_by:
        body_parts.append("🔄 Retweeted by @%s\n" % tweet.retweeted_by)

    body_parts.append(tweet.text)

    if tweet.media:
        body_parts.append("")
        for m in tweet.media:
            icon = "📷" if m.type == "photo" else ("📹" if m.type == "video" else "🎞️")
            body_parts.append("%s %s: %s" % (icon, m.type, m.url))

    if tweet.urls:
        body_parts.append("")
        for url in tweet.urls:
            body_parts.append("🔗 %s" % url)

    if tweet.quoted_tweet:
        qt = tweet.quoted_tweet
        body_parts.append("")
        body_parts.append("┌── Quoted @%s ──" % qt.author.screen_name)
        body_parts.append(qt.text[:200])

    body_parts.append("")
    body_parts.append(
        "❤️ %s  🔄 %s  💬 %s  🔖 %s  👁️ %s"
        % (
            format_number(tweet.metrics.likes),
            format_number(tweet.metrics.retweets),
            format_number(tweet.metrics.replies),
            format_number(tweet.metrics.bookmarks),
            format_number(tweet.metrics.views),
        )
    )
    body_parts.append(
        "🕐 %s · https://x.com/%s/status/%s"
        % (tweet.created_at, tweet.author.screen_name, tweet.id)
    )

    console.print(Panel(
        "\n".join(body_parts),
        title=header,
        border_style="blue",
        expand=True,
    ))


def print_filter_stats(original_count, filtered, console=None):
    # type: (int, List[Tweet], Optional[Console]) -> None
    """Print filter statistics."""
    if console is None:
        console = Console()

    console.print(
        "📊 Filter: %d → %d tweets" % (original_count, len(filtered))
    )
    if filtered:
        top_score = filtered[0].score
        bottom_score = filtered[-1].score
        console.print(
            "   Score range: %.1f ~ %.1f" % (bottom_score, top_score)
        )


def tweets_to_json(tweets):
    # type: (List[Tweet]) -> str
    """Export tweets as JSON string."""
    result = []
    for t in tweets:
        d = {
            "id": t.id,
            "text": t.text,
            "author": {
                "id": t.author.id,
                "name": t.author.name,
                "screenName": t.author.screen_name,
                "profileImageUrl": t.author.profile_image_url,
                "verified": t.author.verified,
            },
            "metrics": {
                "likes": t.metrics.likes,
                "retweets": t.metrics.retweets,
                "replies": t.metrics.replies,
                "quotes": t.metrics.quotes,
                "views": t.metrics.views,
                "bookmarks": t.metrics.bookmarks,
            },
            "createdAt": t.created_at,
            "media": [
                {"type": m.type, "url": m.url, "width": m.width, "height": m.height}
                for m in t.media
            ],
            "urls": t.urls,
            "isRetweet": t.is_retweet,
            "retweetedBy": t.retweeted_by,
            "lang": t.lang,
            "score": t.score,
        }
        if t.quoted_tweet:
            qt = t.quoted_tweet
            d["quotedTweet"] = {
                "id": qt.id,
                "text": qt.text,
                "author": {"screenName": qt.author.screen_name, "name": qt.author.name},
            }
        result.append(d)
    return json.dumps(result, ensure_ascii=False, indent=2)
