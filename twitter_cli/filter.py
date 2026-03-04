"""Tweet filtering and engagement scoring.

Scores tweets by a weighted engagement formula and filters by
configurable rules (topN, min score, language, etc.).
"""

from __future__ import annotations

import math
from typing import Dict, List

from .models import Tweet


# Type alias for filter weights dict
FilterWeights = Dict[str, float]

DEFAULT_WEIGHTS = {
    "likes": 1.0,
    "retweets": 3.0,
    "replies": 2.0,
    "bookmarks": 5.0,
    "views_log": 0.5,
}


def score_tweet(tweet, weights=None):
    # type: (Tweet, FilterWeights) -> float
    """Calculate engagement score for a single tweet.

    Formula:
      score = w_likes × likes
            + w_retweets × retweets
            + w_replies × replies
            + w_bookmarks × bookmarks
            + w_views_log × log10(views)
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS
    m = tweet.metrics
    return (
        weights.get("likes", 1.0) * m.likes
        + weights.get("retweets", 3.0) * m.retweets
        + weights.get("replies", 2.0) * m.replies
        + weights.get("bookmarks", 5.0) * m.bookmarks
        + weights.get("views_log", 0.5) * math.log10(max(m.views, 1))
    )


def filter_tweets(tweets, config):
    # type: (List[Tweet], dict) -> List[Tweet]
    """Filter and rank tweets according to config.

    Config keys:
      mode: "topN" | "score" | "all"
      topN: int
      minScore: float
      lang: list[str]  (empty = no filter)
      excludeRetweets: bool
      weights: dict
    """
    filtered = list(tweets)

    # 1. Language filter
    lang_filter = config.get("lang", [])
    if lang_filter:
        filtered = [t for t in filtered if t.lang in lang_filter]

    # 2. Exclude retweets
    if config.get("excludeRetweets", False):
        filtered = [t for t in filtered if not t.is_retweet]

    # 3. Score all tweets
    weights = config.get("weights", DEFAULT_WEIGHTS)
    for t in filtered:
        t.score = round(score_tweet(t, weights), 1)

    # 4. Sort by score (descending)
    filtered.sort(key=lambda t: t.score, reverse=True)

    # 5. Apply filter mode
    mode = config.get("mode", "topN")
    if mode == "topN":
        top_n = config.get("topN", 20)
        return filtered[:top_n]
    elif mode == "score":
        min_score = config.get("minScore", 50)
        return [t for t in filtered if t.score >= min_score]
    else:
        return filtered
