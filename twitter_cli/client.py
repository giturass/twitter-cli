"""Twitter GraphQL API client.

Uses the same internal GraphQL endpoint that the Twitter web app uses,
authenticated via cookies (auth_token + ct0). QueryId is resolved
dynamically using a three-tier strategy.
"""

from __future__ import annotations

import json
import logging
import math
import re
import ssl
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

from .models import Author, Metrics, Tweet, TweetMedia, UserProfile

logger = logging.getLogger(__name__)

# Public bearer token shared by all Twitter web clients
BEARER_TOKEN = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

# Last-resort fallback query IDs
FALLBACK_QUERY_IDS = {
    "HomeTimeline": "c-CzHF1LboFilMpsx4ZCrQ",
    "Bookmarks": "VFdMm9iVZxlU6hD86gfW_A",
    "CreateTweet": "oB-5XsHNAbjvARJEc8CZFw",
    "DeleteTweet": "VaenaVgh5q5ih7kvyVjgtg",
    "UserByScreenName": "1VOOyvKkiI3FMmkeDNxM9A",
    "UserTweets": "E3opETHurmVJflFsUBVuUQ",
    "Followers": "IOh4aS6UdGWGJUYTqliQ7Q",
    "Following": "zx6e-TLzRkeDO_a7p4b3JQ",
}

# Community-maintained API definition (auto-updated daily)
TWITTER_OPENAPI_URL = (
    "https://raw.githubusercontent.com/fa0311/twitter-openapi/"
    "main/src/config/placeholder.json"
)

# Default features flags required by the GraphQL endpoint
FEATURES = {
    "rweb_video_screen_enabled": False,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": True,
    "responsive_web_jetfuel_frame": False,
    "responsive_web_grok_share_attachment_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "responsive_web_grok_show_grok_translated_post": False,
    "responsive_web_grok_analysis_button_from_backend": False,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_grok_image_annotation_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Module-level cache for query IDs
_cached_query_ids = {}  # type: Dict[str, str]
_bundles_scanned = False


def _create_ssl_context():
    # type: () -> ssl.SSLContext
    """Create a permissive SSL context for urllib."""
    ctx = ssl.create_default_context()
    return ctx


def _url_fetch(url, headers=None):
    # type: (str, Optional[Dict[str, str]]) -> str
    """Simple URL fetch using urllib."""
    req = urllib.request.Request(url)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    ctx = _create_ssl_context()
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        return resp.read().decode("utf-8")


def _scan_bundles():
    # type: () -> None
    """Tier 1: Scan Twitter's main-page JS bundles to extract queryId/operationName pairs."""
    global _bundles_scanned
    if _bundles_scanned:
        return
    _bundles_scanned = True

    try:
        html = _url_fetch("https://x.com", {"user-agent": USER_AGENT})

        script_pattern = re.compile(
            r'(?:src|href)=["\']'
            r'(https://abs\.twimg\.com/responsive-web/client-web[^"\']+\.js)'
            r'["\']'
        )
        script_urls = script_pattern.findall(html)

        for url in script_urls:
            try:
                js = _url_fetch(url)
                op_pattern = re.compile(
                    r'queryId:\s*"([A-Za-z0-9_-]+)"[^}]{0,200}'
                    r'operationName:\s*"([^"]+)"'
                )
                for m in op_pattern.finditer(js):
                    qid, name = m.group(1), m.group(2)
                    if name not in _cached_query_ids:
                        _cached_query_ids[name] = qid
            except Exception:
                continue

        count = len(_cached_query_ids)
        logger.info("Scanned %d JS bundles, found %d operations", len(script_urls), count)
    except Exception as e:
        logger.warning("Failed to scan JS bundles: %s", e)


def _fetch_from_github(operation_name):
    # type: (str) -> Optional[str]
    """Tier 2: Fetch queryId from community-maintained twitter-openapi."""
    try:
        logger.info("Fetching latest queryId from GitHub (twitter-openapi)...")
        data_str = _url_fetch(TWITTER_OPENAPI_URL)
        data = json.loads(data_str)
        op = data.get(operation_name, {})
        qid = op.get("queryId")
        if qid:
            logger.info("Found %s queryId from GitHub: %s", operation_name, qid)
            return qid
        return None
    except Exception as e:
        logger.warning("GitHub lookup failed: %s", e)
        return None


def _resolve_query_id(operation_name):
    # type: (str) -> str
    """Resolve queryId using three-tier strategy: fallback -> GitHub -> bundle scan."""
    if operation_name in _cached_query_ids:
        return _cached_query_ids[operation_name]

    # Tier 1: Hardcoded fallback (instant, no network)
    fallback = FALLBACK_QUERY_IDS.get(operation_name)
    if fallback:
        logger.debug("Using fallback queryId for %s: %s", operation_name, fallback)
        _cached_query_ids[operation_name] = fallback
        return fallback

    logger.info("Auto-detecting %s queryId (no fallback available)...", operation_name)

    # Tier 2: GitHub
    github_id = _fetch_from_github(operation_name)
    if github_id:
        _cached_query_ids[operation_name] = github_id
        return github_id

    # Tier 3: JS bundle scan
    _scan_bundles()
    if operation_name in _cached_query_ids:
        logger.info("Found %s queryId: %s", operation_name, _cached_query_ids[operation_name])
        return _cached_query_ids[operation_name]

    raise RuntimeError(
        'Cannot resolve queryId for "%s" — all detection methods failed' % operation_name
    )


class TwitterClient:
    """Twitter GraphQL API client using cookie authentication."""

    def __init__(self, auth_token, ct0):
        # type: (str, str) -> None
        self._auth_token = auth_token
        self._ct0 = ct0

    def fetch_home_timeline(self, count=20):
        # type: (int) -> List[Tweet]
        """Fetch home timeline tweets."""
        query_id = _resolve_query_id("HomeTimeline")
        return self._fetch_timeline(
            query_id,
            "HomeTimeline",
            count,
            lambda data: _deep_get(data, "data", "home", "home_timeline_urt", "instructions"),
        )

    def fetch_bookmarks(self, count=50):
        # type: (int) -> List[Tweet]
        """Fetch bookmarked tweets."""
        query_id = _resolve_query_id("Bookmarks")

        def get_instructions(data):
            # type: (Any) -> Any
            result = _deep_get(data, "data", "bookmark_timeline", "timeline", "instructions")
            if result is None:
                result = _deep_get(data, "data", "bookmark_timeline_v2", "timeline", "instructions")
            return result

        return self._fetch_timeline(query_id, "Bookmarks", count, get_instructions)

    def _fetch_timeline(self, query_id, operation_name, count, get_instructions, extra_variables=None):
        # type: (str, str, int, Callable, Optional[Dict[str, Any]]) -> List[Tweet]
        """Generic timeline fetcher with pagination and deduplication."""
        tweets = []  # type: List[Tweet]
        cursor = None  # type: Optional[str]
        attempts = 0
        max_attempts = int(math.ceil(count / 20.0)) + 2

        while len(tweets) < count and attempts < max_attempts:
            attempts += 1
            variables = {
                "count": min(count - len(tweets) + 5, 40),
                "includePromotedContent": False,
                "latestControlAvailable": True,
                "requestContext": "launch",
            }  # type: Dict[str, Any]

            if extra_variables:
                variables.update(extra_variables)
            if cursor:
                variables["cursor"] = cursor

            url = "https://x.com/i/api/graphql/%s/%s?" % (query_id, operation_name)
            url += "variables=%s&features=%s" % (
                urllib.request.quote(json.dumps(variables)),
                urllib.request.quote(json.dumps(FEATURES)),
            )

            data = self._api_get(url)
            new_tweets, next_cursor = self._parse_timeline_response(data, get_instructions)

            seen_ids = {t.id for t in tweets}
            for tweet in new_tweets:
                if tweet.id not in seen_ids:
                    tweets.append(tweet)
                    seen_ids.add(tweet.id)

            if not next_cursor or not new_tweets:
                break
            cursor = next_cursor

        return tweets[:count]

    def _build_headers(self):
        # type: () -> Dict[str, str]
        return {
            "Authorization": "Bearer %s" % BEARER_TOKEN,
            "Cookie": "auth_token=%s; ct0=%s" % (self._auth_token, self._ct0),
            "X-Csrf-Token": self._ct0,
            "X-Twitter-Active-User": "yes",
            "X-Twitter-Auth-Type": "OAuth2Session",
            "X-Twitter-Client-Language": "en",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "Referer": "https://x.com/home",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _api_get(self, url):
        # type: (str) -> Any
        """Make authenticated GET request to Twitter API."""
        headers = self._build_headers()
        req = urllib.request.Request(url)
        for k, v in headers.items():
            req.add_header(k, v)

        ctx = _create_ssl_context()
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError("Twitter API error %d: %s" % (e.code, body[:500]))

    def _api_post(self, url, payload):
        # type: (str, Dict[str, Any]) -> Any
        """Make authenticated POST request to Twitter API."""
        headers = self._build_headers()
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        for k, v in headers.items():
            req.add_header(k, v)

        ctx = _create_ssl_context()
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError("Twitter API error %d: %s" % (e.code, body[:500]))

    def create_tweet(self, text, reply_to=None, quote_tweet_url=None):
        # type: (str, Optional[str], Optional[str]) -> Dict[str, Any]
        """Create a tweet, reply, or quote tweet.

        Args:
            text: Tweet text content.
            reply_to: Tweet ID to reply to (optional).
            quote_tweet_url: URL of tweet to quote (optional).

        Returns:
            Dict with tweet_id and text of the created tweet.
        """
        query_id = _resolve_query_id("CreateTweet")
        url = "https://x.com/i/api/graphql/%s/CreateTweet" % query_id

        variables = {
            "tweet_text": text,
            "dark_request": False,
            "media": {"media_entities": [], "possibly_sensitive": False},
            "semantic_annotation_ids": [],
        }  # type: Dict[str, Any]

        if reply_to:
            variables["reply"] = {
                "in_reply_to_tweet_id": reply_to,
                "exclude_reply_user_ids": [],
            }

        if quote_tweet_url:
            variables["attachment_url"] = quote_tweet_url

        features = {
            "communities_web_enable_tweet_community_results_fetch": True,
            "c9s_tweet_anatomy_moderator_badge_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "tweet_awards_web_tipping_enabled": False,
            "creator_subscriptions_quote_tweet_preview_enabled": False,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": True,
            "articles_preview_enabled": True,
            "rweb_video_timestamps_enabled": True,
            "rweb_tipjar_consumption_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_enhance_cards_enabled": False,
        }

        payload = {
            "variables": variables,
            "features": features,
            "queryId": query_id,
        }

        data = self._api_post(url, payload)

        # Parse response
        result = _deep_get(data, "data", "create_tweet", "tweet_results", "result")
        if not result:
            errors = data.get("errors", [])
            if errors:
                raise RuntimeError("CreateTweet failed: %s" % errors[0].get("message", str(errors)))
            raise RuntimeError("CreateTweet failed: unexpected response")

        tweet_id = result.get("rest_id", "")
        tweet_text = _deep_get(result, "legacy", "full_text") or text
        return {"tweet_id": tweet_id, "text": tweet_text}

    def delete_tweet(self, tweet_id):
        # type: (str) -> bool
        """Delete a tweet by ID.

        Returns:
            True if deletion was successful.
        """
        query_id = _resolve_query_id("DeleteTweet")
        url = "https://x.com/i/api/graphql/%s/DeleteTweet" % query_id

        payload = {
            "variables": {"tweet_id": tweet_id, "dark_request": False},
            "queryId": query_id,
        }

        data = self._api_post(url, payload)

        # Check response
        result = _deep_get(data, "data", "delete_tweet", "tweet_results")
        if result is not None:
            return True

        errors = data.get("errors", [])
        if errors:
            raise RuntimeError("DeleteTweet failed: %s" % errors[0].get("message", str(errors)))
        # Some successful deletions return empty result
        return True

    def fetch_user(self, screen_name):
        # type: (str) -> UserProfile
        """Fetch user profile by screen name."""
        query_id = _resolve_query_id("UserByScreenName")
        variables = {
            "screen_name": screen_name,
            "withSafetyModeUserFields": True,
        }
        features = {
            "hidden_profile_subscriptions_enabled": True,
            "rweb_tipjar_consumption_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "subscriptions_verification_info_is_identity_verified_enabled": True,
            "subscriptions_verification_info_verified_since_enabled": True,
            "highlights_tweets_tab_ui_enabled": True,
            "responsive_web_twitter_article_notes_tab_enabled": True,
            "subscriptions_feature_can_gift_premium": True,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "responsive_web_graphql_timeline_navigation_enabled": True,
        }

        url = "https://x.com/i/api/graphql/%s/UserByScreenName?" % query_id
        url += "variables=%s&features=%s" % (
            urllib.request.quote(json.dumps(variables)),
            urllib.request.quote(json.dumps(features)),
        )

        data = self._api_get(url)
        result = _deep_get(data, "data", "user", "result")
        if not result:
            raise RuntimeError("User @%s not found" % screen_name)

        legacy = result.get("legacy", {})
        core = result.get("core", {})
        return UserProfile(
            id=result.get("rest_id", ""),
            name=core.get("name") or legacy.get("name", ""),
            screen_name=core.get("screen_name") or legacy.get("screen_name", screen_name),
            bio=legacy.get("description", ""),
            location=legacy.get("location", ""),
            url=(
                legacy.get("entities", {}).get("url", {}).get("urls", [{}])[0].get("expanded_url", "")
                if legacy.get("entities", {}).get("url")
                else ""
            ),
            followers_count=legacy.get("followers_count", 0),
            following_count=legacy.get("friends_count", 0),
            tweets_count=legacy.get("statuses_count", 0),
            likes_count=legacy.get("favourites_count", 0),
            verified=bool(result.get("is_blue_verified") or legacy.get("verified", False)),
            profile_image_url=legacy.get("profile_image_url_https", ""),
            created_at=legacy.get("created_at", ""),
        )

    def fetch_user_tweets(self, user_id, count=20):
        # type: (str, int) -> List[Tweet]
        """Fetch tweets posted by a user."""
        query_id = _resolve_query_id("UserTweets")
        return self._fetch_timeline(
            query_id,
            "UserTweets",
            count,
            lambda data: _deep_get(data, "data", "user", "result", "timeline_v2", "timeline", "instructions"),
            extra_variables={
                "userId": user_id,
                "withQuickPromoteEligibilityTweetFields": True,
                "withVoice": True,
                "withV2Timeline": True,
            },
        )

    def fetch_followers(self, user_id, count=20):
        # type: (str, int) -> List[UserProfile]
        """Fetch user's followers."""
        query_id = _resolve_query_id("Followers")
        return self._fetch_user_list(query_id, "Followers", user_id, count)

    def fetch_following(self, user_id, count=20):
        # type: (str, int) -> List[UserProfile]
        """Fetch users that this user follows."""
        query_id = _resolve_query_id("Following")
        return self._fetch_user_list(query_id, "Following", user_id, count)

    def _fetch_user_list(self, query_id, operation_name, user_id, count):
        # type: (str, str, str, int) -> List[UserProfile]
        """Generic user list fetcher (followers/following)."""
        variables = {
            "userId": user_id,
            "count": min(count, 50),
            "includePromotedContent": False,
        }  # type: Dict[str, Any]

        url = "https://x.com/i/api/graphql/%s/%s?" % (query_id, operation_name)
        url += "variables=%s&features=%s" % (
            urllib.request.quote(json.dumps(variables)),
            urllib.request.quote(json.dumps(FEATURES)),
        )

        data = self._api_get(url)
        users = []  # type: List[UserProfile]

        instructions = _deep_get(data, "data", "user", "result", "timeline", "timeline", "instructions")
        if not isinstance(instructions, list):
            return users

        for instruction in instructions:
            entries = instruction.get("entries", [])
            for entry in entries:
                content = entry.get("content", {})
                item_content = content.get("itemContent", {})
                user_results = item_content.get("user_results", {}).get("result")
                if not user_results:
                    continue
                legacy = user_results.get("legacy", {})
                core = user_results.get("core", {})
                if not legacy:
                    continue
                users.append(UserProfile(
                    id=user_results.get("rest_id", ""),
                    name=core.get("name") or legacy.get("name", ""),
                    screen_name=core.get("screen_name") or legacy.get("screen_name", ""),
                    bio=legacy.get("description", ""),
                    followers_count=legacy.get("followers_count", 0),
                    following_count=legacy.get("friends_count", 0),
                    verified=bool(user_results.get("is_blue_verified") or legacy.get("verified", False)),
                    profile_image_url=legacy.get("profile_image_url_https", ""),
                ))

        return users[:count]

    def _parse_timeline_response(self, data, get_instructions):
        # type: (Any, Callable) -> Tuple[List[Tweet], Optional[str]]
        """Parse timeline GraphQL response into tweets + next cursor."""
        tweets = []  # type: List[Tweet]
        next_cursor = None  # type: Optional[str]

        try:
            instructions = get_instructions(data)
            if not isinstance(instructions, list):
                logger.warning("No instructions found in response")
                return tweets, next_cursor

            for instruction in instructions:
                entries = instruction.get("entries") or instruction.get("moduleItems") or []

                for entry in entries:
                    content = entry.get("content", {})

                    # Handle cursor entries
                    if content.get("cursorType") == "Bottom" or content.get("entryType") == "TimelineTimelineCursor":
                        val = content.get("value")
                        if val:
                            next_cursor = val
                        continue

                    # Handle single tweet entries
                    item_content = content.get("itemContent", {})
                    tweet_results = item_content.get("tweet_results", {})
                    result = tweet_results.get("result")
                    if result:
                        tweet = self._parse_tweet_result(result)
                        if tweet:
                            tweets.append(tweet)

                    # Handle conversation module (tweet threads)
                    items = content.get("items", [])
                    for item in items:
                        nested = (
                            item.get("item", {})
                            .get("itemContent", {})
                            .get("tweet_results", {})
                            .get("result")
                        )
                        if nested:
                            tweet = self._parse_tweet_result(nested)
                            if tweet:
                                tweets.append(tweet)
        except Exception as e:
            logger.warning("Error parsing timeline response: %s", e)

        return tweets, next_cursor

    def _parse_tweet_result(self, result):
        # type: (Dict[str, Any]) -> Optional[Tweet]
        """Parse a single TweetResult from GraphQL response."""
        try:
            tweet_data = result

            # Handle TweetWithVisibilityResults wrapper
            if result.get("__typename") == "TweetWithVisibilityResults" and result.get("tweet"):
                tweet_data = result["tweet"]

            if tweet_data.get("__typename") == "TweetTombstone":
                return None
            if not tweet_data.get("legacy") or not tweet_data.get("core"):
                return None

            legacy = tweet_data["legacy"]
            user = tweet_data["core"]["user_results"]["result"]
            user_legacy = user.get("legacy", {})
            user_core = user.get("core", {})

            # Check if this is a retweet
            is_retweet = bool(legacy.get("retweeted_status_result", {}).get("result"))
            actual_data = tweet_data
            actual_legacy = legacy
            actual_user = user
            actual_user_legacy = user_legacy

            if is_retweet:
                rt_result = legacy["retweeted_status_result"]["result"]
                # Handle wrapped retweet
                if rt_result.get("__typename") == "TweetWithVisibilityResults" and rt_result.get("tweet"):
                    rt_result = rt_result["tweet"]
                if rt_result.get("legacy") and rt_result.get("core"):
                    actual_data = rt_result
                    actual_legacy = rt_result["legacy"]
                    actual_user = rt_result["core"]["user_results"]["result"]
                    actual_user_legacy = actual_user.get("legacy", {})

            # Parse media
            media = []  # type: List[TweetMedia]
            ext_media = actual_legacy.get("extended_entities", {}).get("media", [])
            for m in ext_media:
                m_type = m.get("type", "")
                if m_type == "photo":
                    media.append(TweetMedia(
                        type="photo",
                        url=m.get("media_url_https", ""),
                        width=_deep_get(m, "original_info", "width"),
                        height=_deep_get(m, "original_info", "height"),
                    ))
                elif m_type in ("video", "animated_gif"):
                    variants = m.get("video_info", {}).get("variants", [])
                    mp4_variants = [v for v in variants if v.get("content_type") == "video/mp4"]
                    mp4_variants.sort(key=lambda v: v.get("bitrate", 0), reverse=True)
                    video_url = mp4_variants[0]["url"] if mp4_variants else m.get("media_url_https", "")
                    media.append(TweetMedia(
                        type=m_type,
                        url=video_url,
                        width=_deep_get(m, "original_info", "width"),
                        height=_deep_get(m, "original_info", "height"),
                    ))

            # Parse URLs
            urls = [u.get("expanded_url", "") for u in actual_legacy.get("entities", {}).get("urls", [])]

            # Parse quoted tweet
            quoted_tweet = None  # type: Optional[Tweet]
            quoted_result = actual_data.get("quoted_status_result", {}).get("result")
            if quoted_result:
                quoted_tweet = self._parse_tweet_result(quoted_result)

            # Extract user info — try user.core (new API), then user.legacy (old API)
            au = actual_user
            aul = actual_user_legacy
            auc = au.get("core", {})
            user_name = auc.get("name") or aul.get("name") or au.get("name", "Unknown")
            user_screen_name = auc.get("screen_name") or aul.get("screen_name") or au.get("screen_name", "unknown")
            user_profile_image = au.get("avatar", {}).get("image_url") or aul.get("profile_image_url_https", "")
            user_verified = au.get("is_blue_verified") or aul.get("verified", False)

            # Retweeted by info
            rt_screen_name = None  # type: Optional[str]
            if is_retweet:
                rt_screen_name = user_core.get("screen_name") or user_legacy.get("screen_name", "unknown")

            return Tweet(
                id=actual_data.get("rest_id", ""),
                text=actual_legacy.get("full_text", ""),
                author=Author(
                    id=au.get("rest_id", ""),
                    name=user_name,
                    screen_name=user_screen_name,
                    profile_image_url=user_profile_image,
                    verified=bool(user_verified),
                ),
                metrics=Metrics(
                    likes=actual_legacy.get("favorite_count", 0),
                    retweets=actual_legacy.get("retweet_count", 0),
                    replies=actual_legacy.get("reply_count", 0),
                    quotes=actual_legacy.get("quote_count", 0),
                    views=int(actual_data.get("views", {}).get("count", "0") or "0"),
                    bookmarks=actual_legacy.get("bookmark_count", 0),
                ),
                created_at=actual_legacy.get("created_at", ""),
                media=media,
                urls=urls,
                is_retweet=is_retweet,
                retweeted_by=rt_screen_name,
                quoted_tweet=quoted_tweet,
                lang=actual_legacy.get("lang", ""),
            )
        except Exception as e:
            logger.warning("Failed to parse tweet: %s", e)
            return None


def _deep_get(d, *keys):
    # type: (Any, *str) -> Any
    """Safely get a nested value from a dict."""
    for key in keys:
        if isinstance(d, dict):
            d = d.get(key)
        else:
            return None
    return d
