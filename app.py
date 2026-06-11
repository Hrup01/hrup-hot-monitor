import base64
import calendar
import html
import json
import os
import queue
import re
import smtplib
import ssl
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from email.message import EmailMessage
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
DATA_DIR = ROOT / "data"
STATE_PATH = DATA_DIR / "state.json"
ENV_PATH = ROOT / ".env"


def load_env_file():
    if not ENV_PATH.exists():
        return
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-5.2").strip()
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "http://localhost:8000").strip()
OPENROUTER_SITE_NAME = os.getenv("OPENROUTER_SITE_NAME", "Hot Monitor").strip()
TWITTERAPI_KEY = os.getenv("TWITTERAPI_KEY", "").strip()

POLL_SECONDS = int(os.getenv("HOTMONITOR_POLL_SECONDS", "1800"))
DEFAULT_PORT = int(os.getenv("PORT", "8000"))

SOURCE_DEFS = [
    {"id": "twitter", "name": "Twitter", "kind": "api"},
    {"id": "bing", "name": "Bing", "kind": "web"},
    {"id": "google", "name": "Google", "kind": "web"},
    {"id": "duckduckgo", "name": "DuckDuckGo", "kind": "web"},
    {"id": "hackernews", "name": "HackerNews", "kind": "web"},
    {"id": "baidu", "name": "Baidu", "kind": "web"},
    {"id": "so360", "name": "360Search", "kind": "web"},
    {"id": "sogou", "name": "Sogou", "kind": "web"},
    {"id": "weixin", "name": "Weixin", "kind": "web"},
    {"id": "zhihu", "name": "Zhihu", "kind": "web"},
    {"id": "bilibili", "name": "Bilibili", "kind": "web"},
    {"id": "weibo", "name": "Weibo", "kind": "web"},
    {"id": "douyin", "name": "Douyin", "kind": "web"},
    {"id": "xiaohongshu", "name": "Xiaohongshu", "kind": "web"},
    {"id": "tieba", "name": "Tieba", "kind": "web"},
]

SOURCE_NAME_BY_ID = {source["id"]: source["name"] for source in SOURCE_DEFS}
SOURCE_RELIABILITY = {
    "twitter": 0.55,
    "bing": 1.00,
    "google": 1.00,
    "duckduckgo": 0.95,
    "hackernews": 1.10,
    "baidu": 0.98,
    "so360": 0.95,
    "sogou": 0.95,
    "weixin": 1.00,
    "zhihu": 0.96,
    "bilibili": 0.90,
    "weibo": 0.90,
    "douyin": 0.90,
    "xiaohongshu": 0.90,
    "tieba": 0.88,
    "manual": 0.85,
}
SOURCE_ITEM_CAPS = {
    "twitter": 3,
    "bing": 5,
    "google": 5,
    "duckduckgo": 4,
    "hackernews": 4,
    "baidu": 5,
    "so360": 5,
    "sogou": 4,
    "weixin": 4,
    "zhihu": 4,
    "bilibili": 4,
    "weibo": 4,
    "douyin": 4,
    "xiaohongshu": 4,
    "tieba": 4,
    "manual": 3,
}

HOTSPOT_SCHEMA = {
    "name": "hotspot_analysis",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "hot_level": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
            "hot_score": {"type": "number"},
            "headline": {"type": "string"},
            "keywords": {"type": "array", "items": {"type": "string"}},
            "source_counts": {"type": "object", "additionalProperties": {"type": "number"}},
            "highlights": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "source": {"type": "string"},
                        "url": {"type": "string"},
                        "author": {"type": "string"},
                        "score": {"type": "number"},
                    },
                    "required": ["text", "source", "url", "author", "score"],
                    "additionalProperties": False,
                },
            },
            "actions": {"type": "array", "items": {"type": "string"}},
            "risk": {"type": "string"},
            "summary": {"type": "string"},
            "reason": {"type": "string"},
            "reason_points": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"},
        },
        "required": ["hot_level", "hot_score", "headline", "keywords", "source_counts", "highlights", "actions", "risk", "summary", "reason", "reason_points", "confidence"],
        "additionalProperties": False,
    },
}


def ensure_dirs():
    DATA_DIR.mkdir(exist_ok=True)


def load_state():
    ensure_dirs()
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "query": "",
        "source_inputs": {s["id"]: "" for s in SOURCE_DEFS},
        "settings": {
            "email_enabled": False,
            "email_to": "",
            "smtp_host": "",
            "smtp_port": 587,
            "smtp_user": "",
            "smtp_password": "",
            "smtp_from": "",
            "push_enabled": True,
            "push_threshold": 70,
        },
        "latest_result": None,
        "history": [],
        "notifications": [],
        "last_checked_at": None,
        "last_error": None,
        "manual_keywords": [],
    }


STATE = load_state()
STATE_LOCK = threading.Lock()
EVENTS: list[queue.Queue] = []


def normalize_state_shape():
    STATE.setdefault("query", "")
    STATE.setdefault("source_inputs", {s["id"]: "" for s in SOURCE_DEFS})
    for source in SOURCE_DEFS:
        STATE["source_inputs"].setdefault(source["id"], "")
    STATE.setdefault("settings", {})
    STATE["settings"].setdefault("email_enabled", False)
    STATE["settings"].setdefault("email_to", "")
    STATE["settings"].setdefault("smtp_host", "")
    STATE["settings"].setdefault("smtp_port", 587)
    STATE["settings"].setdefault("smtp_user", "")
    STATE["settings"].setdefault("smtp_password", "")
    STATE["settings"].setdefault("smtp_from", "")
    STATE["settings"].setdefault("push_enabled", True)
    STATE["settings"].setdefault("push_threshold", 70)
    STATE.setdefault("latest_result", None)
    STATE.setdefault("history", [])
    STATE.setdefault("notifications", [])
    STATE.setdefault("last_checked_at", None)
    STATE.setdefault("last_error", None)
    STATE.setdefault("manual_keywords", [])


normalize_state_shape()


def save_state():
    ensure_dirs()
    STATE_PATH.write_text(json.dumps(STATE, ensure_ascii=False, indent=2), encoding="utf-8")


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def parse_iso_time(value):
    if not value:
        return None
    try:
        return time.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def iso_to_epoch(value):
    parsed = parse_iso_time(value)
    if not parsed:
        return 0
    return int(calendar.timegm(parsed))


def clamp_text(text, limit=5000):
    text = text or ""
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def extract_simple_items(text, limit=12):
    lines = [re.sub(r"\s+", " ", ln).strip(" -\t") for ln in (text or "").splitlines()]
    items = [ln for ln in lines if len(ln) > 6]
    if items:
        return items[:limit]
    words = re.split(r"[,\n;|]+", text or "")
    items = [w.strip() for w in words if len(w.strip()) > 2]
    return items[:limit]


def safe_query(value):
    return urllib.parse.quote_plus(value or "")


ACCOUNT_MARKERS = (
    "\u5b98\u65b9",  # official
    "\u8d26\u53f7",  # account
    "\u535a\u4e3b",  # blogger
    "\u4e3b\u9875",
    "\u4e2a\u4eba\u4e3b\u9875",
    "\u516c\u4f17\u53f7",
    "\u89c6\u9891\u53f7",
    "\u8ba4\u8bc1",
    "up\u4e3b",
    "UP\u4e3b",
    "\u4e3b\u64ad",
    "\u8fbe\u4eba",
    "\u4f5c\u8005",
)

ACCOUNT_PLATFORM_HINTS = {
    "weibo": ("\u5fae\u535a", "weibo"),
    "bilibili": ("b\u7ad9", "bilibili", "\u54d4\u54e9\u54d4\u54e9"),
    "zhihu": ("\u77e5\u4e4e", "zhihu"),
    "douyin": ("\u6296\u97f3", "douyin"),
    "xiaohongshu": ("\u5c0f\u7ea2\u4e66", "xiaohongshu", "xhs"),
    "weixin": ("\u5fae\u4fe1", "\u516c\u4f17\u53f7"),
    "tieba": ("\u8d34\u5427", "tieba"),
}

ACCOUNT_TOPIC_HINTS = (
    "\u65b0\u95fb",
    "\u8d44\u8baf",
    "\u6559\u7a0b",
    "\u4ef7\u683c",
    "\u4e0b\u8f7d",
    "\u6bd4\u8f83",
    "\u8bc4\u6d4b",
    "\u6d41\u91cf",
    "\u5206\u6790",
    "\u653b\u7565",
    "\u6570\u636e",
    "\u6982\u5ff5",
)


def normalize_account_query(query):
    text = (query or "").strip().lstrip("@").strip()
    if not text:
        return ""
    text = re.sub(r"(?i)\b(?:official|account|profile|page|channel)\b", " ", text)
    for marker in ACCOUNT_MARKERS:
        text = text.replace(marker, " ")
    text = re.sub(r"\s+", " ", text).strip(" -_")
    return text or (query or "").strip()


def detect_account_mode(query):
    raw = (query or "").strip()
    if not raw:
        return False, []
    lower = raw.lower()
    platform_ids = []
    for source_id, hints in ACCOUNT_PLATFORM_HINTS.items():
        if any(hint in raw or hint in lower for hint in hints):
            platform_ids.append(source_id)
    explicit = raw.startswith("@") or any(marker in raw for marker in ACCOUNT_MARKERS) or bool(platform_ids)
    short_name = bool(re.fullmatch(r"[\w\u4e00-\u9fff_.-]{2,12}", raw)) and not any(hint in raw for hint in ACCOUNT_TOPIC_HINTS)
    return explicit or short_name, platform_ids


def build_search_targets(query, account_mode=False, platform_ids=None):
    platform_ids = platform_ids or []
    normalized_query = normalize_account_query(query) or (query or "").strip()
    search_query = normalized_query if account_mode else (query or "").strip()
    targets = []

    def add(source_id, url, profile_mode=False):
        targets.append({
            "source_id": source_id,
            "source_name": SOURCE_NAME_BY_ID.get(source_id, source_id),
            "url": url,
            "profile_mode": profile_mode,
        })

    add("baidu", f"https://www.baidu.com/s?wd={safe_query(search_query)}")
    add("so360", f"https://www.so.com/s?q={safe_query(search_query)}")
    add("sogou", f"https://www.sogou.com/web?query={safe_query(search_query)}")
    add("weixin", f"https://weixin.sogou.com/weixin?type=2&query={safe_query(search_query)}")
    add("zhihu", f"https://www.zhihu.com/search?type=content&q={safe_query(search_query)}")
    add("bilibili", f"https://search.bilibili.com/all?keyword={safe_query(search_query)}")
    add("weibo", f"https://s.weibo.com/weibo?q={safe_query(search_query)}")
    add("douyin", f"https://www.douyin.com/search/{urllib.parse.quote(search_query)}?type=general")
    add("xiaohongshu", f"https://www.xiaohongshu.com/search_result?keyword={safe_query(search_query)}&source=web_search")
    add("tieba", f"https://tieba.baidu.com/f/search/res?ie=utf-8&qw={safe_query(search_query)}")
    add("bing", f"https://www.bing.com/search?q={safe_query(search_query)}&setlang=zh-cn")
    add("google", f"https://www.google.com/search?q={safe_query(search_query)}&hl=zh-CN")
    add("duckduckgo", f"https://html.duckduckgo.com/html/?q={safe_query(search_query)}")
    add("hackernews", f"https://hn.algolia.com/?query={safe_query(search_query)}&sort=byPopularity&prefix=false&page=0")

    if account_mode:
        profile_sources = {
            "weibo": f"https://s.weibo.com/user?q={safe_query(normalized_query)}",
            "zhihu": f"https://www.zhihu.com/search?type=people&q={safe_query(normalized_query)}",
            "bilibili": f"https://search.bilibili.com/upuser?keyword={safe_query(normalized_query)}",
            "douyin": f"https://www.douyin.com/search/{urllib.parse.quote(normalized_query)}?type=user",
            "weixin": f"https://weixin.sogou.com/weixin?type=2&query={safe_query(normalized_query)}",
            "xiaohongshu": f"https://www.xiaohongshu.com/search_result?keyword={safe_query(normalized_query)}&source=web_search",
        }
        if platform_ids:
            for source_id in platform_ids:
                url = profile_sources.get(source_id)
                if url:
                    add(source_id, url, True)
        else:
            for source_id, url in profile_sources.items():
                add(source_id, url, True)

        for domain in ("weibo.com", "zhihu.com", "bilibili.com", "douyin.com", "xiaohongshu.com", "weixin.qq.com"):
            site_query = f"site:{domain} {normalized_query}"
            add("baidu", f"https://www.baidu.com/s?wd={safe_query(site_query)}", True)
            add("so360", f"https://www.so.com/s?q={safe_query(site_query)}", True)
            add("sogou", f"https://www.sogou.com/web?query={safe_query(site_query)}", True)

    return targets


def query_tokens(query):
    tokens = []
    for token in re.findall(r"[\w\u4e00-\u9fff]{2,}", (query or "").lower()):
        if token not in {"and", "or", "the", "for", "with", "that", "this"}:
            tokens.append(token)
    return tokens


def build_source_counts(items):
    source_map = {}
    for item in items:
        source = item.get("source") or "unknown"
        source_map[source] = source_map.get(source, 0) + 1
    return source_map


def score_item(query, item):
    text = clamp_text(item.get("text") or "", 500)
    norm = re.sub(r"\s+", " ", text.lower()).strip()
    tokens = query_tokens(query)
    source_id = (item.get("source_id") or "").strip().lower()
    score = 18.0

    score += (SOURCE_RELIABILITY.get(source_id, 0.85) - 1.0) * 18.0

    if tokens:
        matched = sum(1 for token in tokens if token in norm)
        if matched:
            score += min(24.0, matched * 5.0)
        if " ".join(tokens[:3]) in norm:
            score += 6.0

    length = len(text)
    if length < 24:
        score -= 10.0
    elif length < 60:
        score -= 4.0
    elif length > 180:
        score += 4.0
    elif length > 90:
        score += 2.0

    boilerplate_signals = (
        "sign in",
        "log in",
        "cookie",
        "privacy policy",
        "terms of service",
        "javascript",
        "enable javascript",
        "search results",
        "next page",
        "more results",
        "open app",
        "download app",
    )
    if any(signal in norm for signal in boilerplate_signals):
        score -= 15.0

    if item.get("profile_mode"):
        score += 10.0

    if source_id == "twitter":
        metrics = item.get("metrics") or {}
        likes = int(metrics.get("likes") or 0)
        reposts = int(metrics.get("reposts") or 0)
        replies = int(metrics.get("replies") or 0)
        views = int(metrics.get("views") or 0)
        engagement = likes + (reposts * 2) + (replies * 2) + (views // 2000)
        if engagement == 0:
            score -= 12.0
        elif engagement <= 3:
            score -= 8.0
        elif engagement <= 10:
            score -= 4.0
        if likes + reposts + replies <= 3:
            score -= 8.0
        elif likes + reposts + replies <= 6:
            score -= 4.0
        if replies <= 1:
            score -= 5.0
        if text.startswith("@") or norm.startswith("rt @") or text.count("@") >= 2:
            score -= 8.0
    else:
        if source_id in {"bing", "google", "duckduckgo", "hackernews", "baidu", "so360", "sogou", "weixin", "zhihu", "bilibili", "weibo", "douyin", "xiaohongshu", "tieba"} and length >= 60:
            score += 2.0

    return max(0, min(100, int(round(score))))


def prepare_analysis_items(query, items):
    scored_items = []
    for item in items:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        scored_item = dict(item)
        scored_item["score"] = score_item(query, scored_item)
        scored_items.append(scored_item)

    scored_items.sort(
        key=lambda item: (
            item.get("score", 0),
            SOURCE_RELIABILITY.get((item.get("source_id") or "").strip().lower(), 0.85),
            len(item.get("text") or ""),
        ),
        reverse=True,
    )

    selected_items = []
    source_counts = {}
    for item in scored_items:
        source_id = (item.get("source_id") or "unknown").strip().lower()
        cap = SOURCE_ITEM_CAPS.get(source_id, 4)
        if source_counts.get(source_id, 0) >= cap:
            continue
        selected_items.append(item)
        source_counts[source_id] = source_counts.get(source_id, 0) + 1
        if len(selected_items) >= 40:
            break

    if not selected_items:
        selected_items = scored_items[:20]
    return scored_items, selected_items


def fetch_url(url, headers=None, timeout=12):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
        return data.decode(charset, errors="replace")


def parse_html_snippets(html_text, source_name, max_items=8, profile_mode=False):
    snippets = []
    fetched_at = now_iso()
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html_text)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    meta_matches = re.findall(
        r'(?is)<meta[^>]+(?:name|property)=["\'](?:description|og:description|og:title|twitter:title|twitter:description)["\'][^>]+content=["\'](.*?)["\']',
        text,
    )
    for meta in meta_matches[:2]:
        meta = html.unescape(re.sub(r"\s+", " ", meta)).strip()
        if len(meta) >= 12 and meta not in {s["text"] for s in snippets}:
            snippets.append({
                "source": source_name,
                "text": meta[:220],
                "raw_description": meta[:220],
                "url": "",
                "author": "",
                "metrics": {},
                "fetched_at": fetched_at,
                "published_at": extract_published_at(meta, fetched_at),
                "description_kind": "meta",
                "profile_mode": profile_mode,
            })
    for match in re.finditer(r'(?is)<a[^>]*href=["\'](.*?)["\'][^>]*>(.*?)</a>', text):
        href = html.unescape(match.group(1)).strip()
        raw = html.unescape(re.sub(r"\s+", " ", re.sub(r"(?is)<.*?>", " ", match.group(2)))).strip()
        if len(raw) < 12:
            continue
        if raw not in {s["text"] for s in snippets}:
            snippets.append({
                "source": source_name,
                "text": raw[:220],
                "raw_description": raw[:220],
                "url": href,
                "author": "",
                "metrics": {},
                "fetched_at": fetched_at,
                "published_at": extract_published_at(raw, fetched_at),
                "description_kind": "link",
                "profile_mode": profile_mode,
            })
        if len(snippets) >= max_items:
            break
    blocks = re.findall(r"(?is)<h[1-4][^>]*>(.*?)</h[1-4]>|<title[^>]*>(.*?)</title>|<a[^>]*>(.*?)</a>", text)
    for block in blocks:
        raw = next((b for b in block if b), "")
        raw = re.sub(r"(?is)<.*?>", " ", raw)
        raw = html.unescape(re.sub(r"\s+", " ", raw)).strip()
        if len(raw) < 12:
            continue
        if raw not in {s["text"] for s in snippets}:
            snippets.append({
                "source": source_name,
                "text": raw[:220],
                "raw_description": raw[:220],
                "url": "",
                "author": "",
                "metrics": {},
                "fetched_at": fetched_at,
                "published_at": extract_published_at(raw, fetched_at),
                "description_kind": "text",
                "profile_mode": profile_mode,
            })
        if len(snippets) >= max_items:
            break
    if not snippets:
        plain = html.unescape(re.sub(r"<[^>]+>", " ", html_text))
        candidates = [re.sub(r"\s+", " ", x).strip() for x in re.split(r"[。.!?\n\r]+", plain)]
        for candidate in candidates:
            if len(candidate) > 18:
                snippets.append({
                    "source": source_name,
                    "text": candidate[:220],
                    "raw_description": candidate[:220],
                    "url": "",
                    "author": "",
                    "metrics": {},
                    "fetched_at": fetched_at,
                    "published_at": extract_published_at(candidate, fetched_at),
                    "description_kind": "plain",
                    "profile_mode": profile_mode,
                })
            if len(snippets) >= max_items:
                break
    return snippets


def fetch_twitter(query):
    if not TWITTERAPI_KEY:
        return [], "missing twitterapi key"
    since = int(time.time()) - 6 * 3600
    until = int(time.time())
    q = f"{query} since_time:{since} until_time:{until}"
    url = "https://api.twitterapi.io/twitter/tweet/advanced_search?" + urllib.parse.urlencode({
        "query": q,
        "queryType": "Latest",
    })
    data = fetch_url(url, headers={"X-API-Key": TWITTERAPI_KEY})
    payload = json.loads(data)
    items = []
    fetched_at = now_iso()
    for t in payload.get("tweets", [])[:20]:
        author = t.get("author") or {}
        metrics = {
            "likes": int(t.get("likeCount") or 0),
            "reposts": int(t.get("retweetCount") or 0),
            "replies": int(t.get("replyCount") or 0),
            "views": int(t.get("viewCount") or 0),
        }
        published_at = (
            t.get("createdAt")
            or t.get("created_at")
            or t.get("tweetCreatedAt")
            or t.get("createdTime")
            or t.get("date")
        )
        items.append({
            "source_id": "twitter",
            "source": "Twitter",
            "text": clamp_text(t.get("text") or ""),
            "raw_description": clamp_text(t.get("text") or ""),
            "url": t.get("url") or "",
            "author": author.get("userName") or author.get("name") or "",
            "metrics": metrics,
            "published_at": extract_published_at(published_at or t.get("text") or "", fetched_at) if published_at or t.get("text") else None,
            "fetched_at": fetched_at,
            "description_kind": "tweet",
        })
    return items, None


def fetch_web_source(source_id, source_name, url, profile_mode=False):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    html_text = fetch_url(url, headers=headers)
    snippets = parse_html_snippets(html_text, source_name, profile_mode=profile_mode)
    for snippet in snippets:
        snippet["source_id"] = source_id
        snippet["profile_mode"] = profile_mode
    return snippets


def collect_source_items(query, manual_inputs):
    items = []
    errors = {}
    account_mode, platform_ids = detect_account_mode(query)
    fetched_at = now_iso()
    if manual_inputs.get("twitter") or TWITTERAPI_KEY:
        try:
            source_items, err = fetch_twitter(query or manual_inputs.get("twitter", ""))
            items.extend(source_items)
            if err:
                errors["twitter"] = err
        except Exception as exc:
            errors["twitter"] = str(exc)

    web_targets = build_search_targets(query, account_mode=account_mode, platform_ids=platform_ids)
    for target in web_targets:
        try:
            items.extend(fetch_web_source(target["source_id"], target["source_name"], target["url"], profile_mode=target["profile_mode"]))
        except Exception as exc:
            errors[target["source_id"]] = str(exc)

    for sid, raw in manual_inputs.items():
        if raw and sid != "twitter":
            for idx, text in enumerate(extract_simple_items(raw)):
                items.append({
                    "source_id": sid,
                    "source": SOURCE_NAME_BY_ID.get(sid, sid),
                    "text": text,
                    "raw_description": text,
                    "url": "",
                    "author": f"manual-{idx + 1}",
                    "metrics": {},
                    "fetched_at": fetched_at,
                    "published_at": extract_published_at(text, fetched_at),
                    "description_kind": "manual",
                })
    return items, errors


def heuristic_analyze(query, items, source_counts=None):
    ranked = sorted(
        [
            {
                "text": item.get("text", ""),
                "score": item.get("score", score_item(query, item)),
                "source": item.get("source", "unknown"),
                "url": item.get("url", ""),
                "author": item.get("author", ""),
            }
            for item in items
            if (item.get("text") or "").strip()
        ],
        key=lambda x: x["score"],
        reverse=True,
    )
    top = ranked[:8]
    max_score = top[0]["score"] if top else 0
    level = "low"
    if max_score >= 85:
        level = "critical"
    elif max_score >= 70:
        level = "high"
    elif max_score >= 50:
        level = "medium"
    keywords = []
    for item in top:
        for chunk in re.split(r"[^\w\u4e00-\u9fff]+", item["text"]):
            if len(chunk) >= 2 and chunk not in keywords:
                keywords.append(chunk)
            if len(keywords) >= 8:
                break
        if len(keywords) >= 8:
            break
    reason_points = []
    if keywords:
        reason_points.append(f"命中关键词：{', '.join(keywords[:4])}")
    if source_counts:
        reason_points.append(f"来源覆盖：{len(source_counts)} 个来源")
    if top:
        reason_points.append(f"高分证据：{top[0]['source']} / {top[0]['score']} 分")
    if len(top) > 1:
        reason_points.append(f"补充证据：{len(top)} 条高分片段")
    confidence = max(30, min(95, 40 + len(source_counts or {}) * 5 + (max_score // 3)))
    return {
        "hot_level": level,
        "hot_score": max_score,
        "headline": top[0]["text"] if top else "鏆傛棤瓒冲淇″彿",
        "keywords": keywords,
        "source_counts": source_counts if source_counts is not None else build_source_counts(items),
        "highlights": top,
        "reason": "；".join(reason_points[:4]) if reason_points else "根据多源命中、关键词重合与热度分综合判断。",
        "reason_points": reason_points[:6],
        "confidence": confidence,
        "actions": [
            "缁х画瑙傚療楂樺垎鏉ユ簮鐨勫闀块€熷害",
            "瀵瑰悓棰樻潗鐨勪笉鍚岃〃杩板仛鍘婚噸鑱氬悎",
            "濡傛灉鍒嗘暟鎸佺画涓婂崌锛屾帹閫佺粰璁㈤槄浜?",
        ],
        "risk": "闇€瑕佺粨鍚堟椂鏁堜笌閲嶅鍑虹幇棰戞鍐嶇‘璁ゆ槸鍚﹁繘鍏ョ垎鍙戞湡",
    }


def openrouter_analyze(query, items, source_counts, raw_source_counts=None):
    if not OPENROUTER_API_KEY:
        raise RuntimeError("missing OPENROUTER_API_KEY")
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a hot topic analyst. "
                    "Keep the response concise and evidence-driven."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({
                    "query": query,
                    "source_counts": source_counts,
                    "raw_source_counts": raw_source_counts or source_counts,
                    "items": items[:40],
                    "selection_policy": {
                        "source_reliability": SOURCE_RELIABILITY,
                        "source_item_caps": SOURCE_ITEM_CAPS,
                    },
                }, ensure_ascii=False),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": HOTSPOT_SCHEMA,
        },
        "temperature": 0.2,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": OPENROUTER_SITE_URL,
            "X-OpenRouter-Title": OPENROUTER_SITE_NAME,
        },
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        reply = json.loads(resp.read().decode("utf-8"))
    content = reply["choices"][0]["message"]["content"]
    content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.I | re.M).strip()
    return json.loads(content)


def send_email(subject, body):
    settings = STATE["settings"]
    if not settings.get("email_enabled"):
        return False, "email disabled"
    required = ["smtp_host", "smtp_port", "smtp_user", "smtp_password", "smtp_from", "email_to"]
    if not all(settings.get(k) for k in required):
        return False, "incomplete email settings"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings["smtp_from"]
    msg["To"] = settings["email_to"]
    msg.set_content(body)
    context = ssl.create_default_context()
    with smtplib.SMTP(settings["smtp_host"], int(settings["smtp_port"]), timeout=20) as server:
        server.starttls(context=context)
        server.login(settings["smtp_user"], settings["smtp_password"])
        server.send_message(msg)
    return True, None


def broadcast(event):
    stale = []
    for q in EVENTS:
        try:
            q.put_nowait(event)
        except Exception:
            stale.append(q)
    for q in stale:
        try:
            EVENTS.remove(q)
        except ValueError:
            pass


def display_level(level, score=0):
    if level == "critical" or score >= 90:
        return "URGENT"
    if level == "high" or score >= 70:
        return "HIGH"
    if level == "medium" or score >= 50:
        return "MEDIUM"
    return "LOW"


def short_summary(result, highlight):
    summary = result.get("summary") or result.get("risk") or ""
    if summary:
        return summary[:140]
    text = highlight.get("text") or result.get("headline") or ""
    return text[:140]


def short_text(value, limit=220):
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text[:limit]


def normalize_metric_value(value):
    try:
        if value is None or value == "":
            return 0
        if isinstance(value, str) and value.endswith("万"):
            return int(float(value[:-1]) * 10000)
        return int(float(value))
    except Exception:
        return 0


def normalize_metrics(item):
    metrics = item.get("metrics") or {}
    return {
        "likes": normalize_metric_value(metrics.get("likes") or metrics.get("like_count") or metrics.get("likeCount")),
        "replies": normalize_metric_value(metrics.get("replies") or metrics.get("comments") or metrics.get("comment_count") or metrics.get("replyCount")),
        "reposts": normalize_metric_value(metrics.get("reposts") or metrics.get("shares") or metrics.get("retweets") or metrics.get("retweetCount")),
        "bookmarks": normalize_metric_value(metrics.get("bookmarks") or metrics.get("favorites") or metrics.get("collects") or metrics.get("bookmarksCount")),
        "views": normalize_metric_value(metrics.get("views") or metrics.get("impressions") or metrics.get("viewCount")),
    }


def interaction_total(metrics):
    return sum(max(0, int(value or 0)) for value in metrics.values())


def iso_from_epoch(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def format_reference_epoch(reference_at=None):
    if reference_at:
        epoch = iso_to_epoch(reference_at)
        if epoch:
            return epoch
    return int(time.time())


def extract_published_at(text, reference_at=None):
    raw = short_text(text, 200)
    if not raw:
        return None
    if raw.isdigit():
        try:
            value = int(raw)
            if value > 10**12:
                value = int(value / 1000)
            if value > 10**9:
                return iso_from_epoch(value)
        except Exception:
            pass
    reference_epoch = format_reference_epoch(reference_at)
    current_year = time.gmtime(reference_epoch).tm_year

    patterns = [
        (r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?", True),
        (r"(\d{4})年(\d{1,2})月(\d{1,2})日(?:\s*(\d{1,2}):(\d{2}))?", True),
        (r"(\d{1,2})[-/.](\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?", False),
        (r"(\d{1,2})月(\d{1,2})日(?:\s*(\d{1,2}):(\d{2}))?", False),
    ]
    for pattern, has_year in patterns:
        match = re.search(pattern, raw)
        if not match:
            continue
        groups = match.groups()
        if has_year:
            year = int(groups[0])
            month = int(groups[1])
            day = int(groups[2])
            hour = int(groups[3] or 0)
            minute = int(groups[4] or 0)
        else:
            year = current_year
            month = int(groups[0])
            day = int(groups[1])
            hour = int(groups[2] or 0)
            minute = int(groups[3] or 0)
        try:
            return iso_from_epoch(calendar.timegm((year, month, day, hour, minute, 0, 0, 0, 0)))
        except Exception:
            continue

    relative = re.search(r"(\d+)\s*(分钟|分|小时|天)前", raw)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2)
        delta = amount * 60 if unit in {"分钟", "分"} else amount * 3600 if unit == "小时" else amount * 86400
        return iso_from_epoch(max(0, reference_epoch - delta))
    if "昨天" in raw:
        return iso_from_epoch(max(0, reference_epoch - 86400))
    if "今天" in raw:
        return iso_from_epoch(reference_epoch)
    return None


def collect_reason_points(result, aggregate):
    points = []
    keywords = [str(x).strip() for x in (result.get("keywords") or []) if str(x).strip()]
    if keywords:
        points.append(f"关键词命中：{', '.join(keywords[:4])}")
    if aggregate.get("source_count"):
        points.append(f"多源覆盖：{aggregate['source_count']} 个来源")
    if aggregate.get("appearances", 0) > 1:
        points.append(f"历史出现：{aggregate['appearances']} 次")
    trend = aggregate.get("trend_label")
    if trend and aggregate.get("trend_delta") is not None:
        points.append(f"趋势：{trend} ({aggregate['trend_delta']:+d})")
    if result.get("reason_points"):
        points.extend([str(x).strip() for x in result.get("reason_points") if str(x).strip()])
    if result.get("reason"):
        points.append(str(result.get("reason")).strip())
    if result.get("actions"):
        points.append(f"建议动作：{short_text(result.get('actions')[0], 80)}")
    return [point for point in dict.fromkeys(points) if point]


def build_reason_text(result, aggregate):
    points = collect_reason_points(result, aggregate)
    if points:
        return "；".join(points[:4])
    return short_summary(result, {"text": aggregate.get("raw_description") or aggregate.get("title") or ""})


def normalize_evidence_key(item):
    text = item.get("raw_description") or item.get("text") or ""
    return normalize_hotspot_key(text)


def score_evidence(item):
    metrics = normalize_metrics(item)
    return (
        int(item.get("score") or 0),
        interaction_total(metrics),
        1 if item.get("published_at") else 0,
        1 if item.get("fetched_at") else 0,
        len(short_text(item.get("raw_description") or item.get("text") or "", 220)),
    )


def build_evidence_item(item, highlight=None, result=None):
    metrics = normalize_metrics(item)
    text = short_text(item.get("raw_description") or item.get("text") or (highlight or {}).get("text") or "", 260)
    fetched_at = item.get("fetched_at") or (result or {}).get("analyzed_at") or STATE.get("last_checked_at")
    published_at = item.get("published_at") or extract_published_at(text, fetched_at)
    return {
        "text": text,
        "raw_description": text,
        "source": item.get("source") or (highlight or {}).get("source") or "unknown",
        "source_id": item.get("source_id") or "unknown",
        "url": item.get("url") or (highlight or {}).get("url") or "",
        "author": item.get("author") or (highlight or {}).get("author") or "",
        "score": int(item.get("score") or (highlight or {}).get("score") or (result or {}).get("hot_score") or 0),
        "fetched_at": fetched_at,
        "published_at": published_at,
        "metrics": metrics,
        "interaction_total": interaction_total(metrics),
        "description_kind": item.get("description_kind") or "raw",
    }


def pick_best_evidence(evidence_items):
    if not evidence_items:
        return None
    return sorted(evidence_items, key=score_evidence, reverse=True)[0]


def normalize_hotspot_key(text):
    normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
    return normalized[:160]


def level_rank(level):
    return {
        "LOW": 1,
        "MEDIUM": 2,
        "HIGH": 3,
        "URGENT": 4,
    }.get(str(level or "LOW").upper(), 1)


def build_hotspot_cards(results):
    aggregates = {}
    now_epoch = int(time.time())
    new_cutoff = now_epoch - 24 * 3600

    def add_evidence(aggregate, evidence_item):
        if not evidence_item:
            return
        evidence_key = "|".join([
            normalize_hotspot_key(evidence_item.get("text")),
            evidence_item.get("source_id") or "",
            evidence_item.get("url") or "",
            evidence_item.get("published_at") or "",
            evidence_item.get("fetched_at") or "",
        ])
        if evidence_key in aggregate["_evidence_keys"]:
            return
        aggregate["_evidence_keys"].add(evidence_key)
        aggregate["_evidence"].append(evidence_item)

    for result in results:
        if not isinstance(result, dict):
            continue

        result_items = []
        for field in ("items", "raw_items"):
            value = result.get(field) or []
            if isinstance(value, list):
                result_items.extend([item for item in value if isinstance(item, dict)])

        item_lookup = {}
        for item in result_items:
            key = normalize_evidence_key(item)
            if not key:
                continue
            item_lookup.setdefault(key, []).append(item)

        highlights = result.get("highlights") or []
        if not highlights and result.get("headline"):
            highlights = [{
                "text": result.get("headline", ""),
                "source": "AI",
                "url": "",
                "author": "",
                "score": result.get("hot_score", 0),
            }]

        result_seen = set()
        analyzed_at = result.get("analyzed_at") or STATE.get("last_checked_at") or now_iso()
        analyzed_epoch = iso_to_epoch(analyzed_at)
        for idx, highlight in enumerate(highlights[:8]):
            text = (highlight.get("text") or "").strip()
            if not text:
                continue
            key = normalize_hotspot_key(text)
            if key in result_seen:
                continue
            result_seen.add(key)

            score = int(highlight.get("score") or result.get("hot_score") or 0)
            level = display_level(result.get("hot_level"), score)
            source = highlight.get("source") or "unknown"
            evidence_candidates = []
            for candidate_key in (key, normalize_hotspot_key(source)):
                evidence_candidates.extend(item_lookup.get(candidate_key, []))
            if not evidence_candidates:
                for item in result_items:
                    item_text = normalize_hotspot_key(item.get("text") or item.get("raw_description") or "")
                    if item_text and (item_text in key or key in item_text):
                        evidence_candidates.append(item)

            if not evidence_candidates:
                evidence_candidates = [{
                    "source_id": source.lower(),
                    "source": source,
                    "text": text,
                    "raw_description": text,
                    "url": highlight.get("url") or "",
                    "author": highlight.get("author") or "",
                    "score": score,
                    "fetched_at": analyzed_at,
                    "published_at": extract_published_at(text, analyzed_at),
                    "metrics": {},
                    "description_kind": "highlight",
                }]

            evidence_items = [build_evidence_item(item, highlight, result) for item in evidence_candidates[:4]]
            best_evidence = pick_best_evidence(evidence_items) or {}
            aggregate = aggregates.setdefault(key, {
                "id": f"{result.get('analyzed_at', 'hot')}-{idx}",
                "level": level,
                "score": score,
                "source": source,
                "topic": result.get("query") or STATE.get("query") or "",
                "title": text,
                "summary": short_summary(result, highlight),
                "ai_summary": short_summary(result, highlight),
                "raw_description": best_evidence.get("raw_description") or text,
                "tags": list((result.get("keywords") or [])[:3]),
                "url": best_evidence.get("url") or highlight.get("url") or "",
                "author": best_evidence.get("author") or highlight.get("author") or "",
                "analyzed_at": analyzed_at,
                "mode": result.get("mode") or "unknown",
                "reason": result.get("reason") or "",
                "reason_points": list(result.get("reason_points") or []),
                "confidence": result.get("confidence") or 0,
                "evidence": [],
                "interactions": best_evidence.get("metrics") or {},
                "interaction_total": best_evidence.get("interaction_total") or 0,
                "published_at": best_evidence.get("published_at") or analyzed_at,
                "last_published_at": best_evidence.get("published_at") or analyzed_at,
                "fetched_at": best_evidence.get("fetched_at") or analyzed_at,
                "last_fetched_at": best_evidence.get("fetched_at") or analyzed_at,
                "first_seen_at": analyzed_at,
                "last_seen_at": analyzed_at,
                "_sources": set(),
                "_first_seen_epoch": None,
                "_last_seen_epoch": 0,
                "_history_points": [],
                "_published_epochs": [],
                "_fetched_epochs": [],
                "_evidence_keys": set(),
                "_evidence": [],
                "appearances": 0,
                "trend_label": "平稳",
                "trend_delta": 0,
            })

            aggregate["appearances"] += 1
            aggregate["_sources"].add(source)
            aggregate["topic"] = aggregate["topic"] or result.get("query") or STATE.get("query") or ""
            aggregate["tags"] = list(dict.fromkeys([*aggregate["tags"], *((result.get("keywords") or [])[:3])]))[:5]
            aggregate["_history_points"].append({"analyzed_at": analyzed_at, "score": score})
            if best_evidence:
                add_evidence(aggregate, best_evidence)
                aggregate["raw_description"] = aggregate.get("raw_description") or best_evidence.get("raw_description") or text
                aggregate["url"] = aggregate.get("url") or best_evidence.get("url") or ""
                aggregate["author"] = aggregate.get("author") or best_evidence.get("author") or ""
                aggregate["interactions"] = aggregate["interactions"] or best_evidence.get("metrics") or {}
                aggregate["interaction_total"] = max(aggregate.get("interaction_total") or 0, best_evidence.get("interaction_total") or 0)
                if best_evidence.get("published_at"):
                    aggregate["_published_epochs"].append(iso_to_epoch(best_evidence.get("published_at")))
                    if not aggregate.get("published_at") or iso_to_epoch(best_evidence.get("published_at")) < iso_to_epoch(aggregate.get("published_at")):
                        aggregate["published_at"] = best_evidence.get("published_at")
                    if not aggregate.get("last_published_at") or iso_to_epoch(best_evidence.get("published_at")) >= iso_to_epoch(aggregate.get("last_published_at")):
                        aggregate["last_published_at"] = best_evidence.get("published_at")
                if best_evidence.get("fetched_at"):
                    aggregate["_fetched_epochs"].append(iso_to_epoch(best_evidence.get("fetched_at")))
                    if not aggregate.get("fetched_at") or iso_to_epoch(best_evidence.get("fetched_at")) < iso_to_epoch(aggregate.get("fetched_at")):
                        aggregate["fetched_at"] = best_evidence.get("fetched_at")
                    if not aggregate.get("last_fetched_at") or iso_to_epoch(best_evidence.get("fetched_at")) >= iso_to_epoch(aggregate.get("last_fetched_at")):
                        aggregate["last_fetched_at"] = best_evidence.get("fetched_at")

            aggregate["_published_epochs"] = [epoch for epoch in aggregate["_published_epochs"] if epoch > 0]
            aggregate["_fetched_epochs"] = [epoch for epoch in aggregate["_fetched_epochs"] if epoch > 0]
            if aggregate["_first_seen_epoch"] is None or (analyzed_epoch and analyzed_epoch < aggregate["_first_seen_epoch"]):
                aggregate["_first_seen_epoch"] = analyzed_epoch
                aggregate["first_seen_at"] = analyzed_at
            if analyzed_epoch >= aggregate["_last_seen_epoch"]:
                aggregate["_last_seen_epoch"] = analyzed_epoch
                aggregate["last_seen_at"] = analyzed_at
                aggregate["analyzed_at"] = analyzed_at
                aggregate["mode"] = result.get("mode") or aggregate["mode"]
                aggregate["reason"] = result.get("reason") or aggregate["reason"]
                aggregate["reason_points"] = list(result.get("reason_points") or aggregate["reason_points"])
                aggregate["confidence"] = result.get("confidence") or aggregate["confidence"]
                aggregate["ai_summary"] = short_summary(result, highlight)
                aggregate["summary"] = aggregate["ai_summary"]

            if score > aggregate["score"]:
                aggregate["score"] = score
                aggregate["level"] = level
                aggregate["source"] = source
            elif level_rank(level) > level_rank(aggregate["level"]):
                aggregate["level"] = level

            if len(aggregate["_evidence"]) > 12:
                aggregate["_evidence"] = sorted(aggregate["_evidence"], key=score_evidence, reverse=True)[:8]

    cards = []
    for aggregate in aggregates.values():
        sources = sorted(aggregate.pop("_sources"))
        first_seen_epoch = aggregate.pop("_first_seen_epoch") or 0
        last_seen_epoch = aggregate.pop("_last_seen_epoch") or 0
        history_points = sorted(aggregate.pop("_history_points"), key=lambda x: iso_to_epoch(x.get("analyzed_at")))
        published_epochs = sorted(aggregate.pop("_published_epochs"))
        fetched_epochs = sorted(aggregate.pop("_fetched_epochs"))
        evidence_items = sorted(aggregate.pop("_evidence"), key=score_evidence, reverse=True)
        aggregate["source_count"] = len(sources)
        aggregate["sources"] = sources
        aggregate["is_new"] = first_seen_epoch >= new_cutoff if first_seen_epoch else False
        aggregate["is_resonating"] = aggregate["source_count"] >= 3
        aggregate["first_seen_at"] = aggregate.get("first_seen_at") or aggregate.get("analyzed_at")
        aggregate["last_seen_at"] = aggregate.get("last_seen_at") or aggregate.get("analyzed_at")
        aggregate["freshness_hours"] = max(0, int((now_epoch - last_seen_epoch) / 3600)) if last_seen_epoch else None
        aggregate["evidence"] = evidence_items[:5]
        aggregate["evidence_count"] = len(evidence_items)
        aggregate["published_at"] = iso_from_epoch(published_epochs[0]) if published_epochs else aggregate.get("published_at") or aggregate.get("analyzed_at")
        aggregate["last_published_at"] = iso_from_epoch(published_epochs[-1]) if published_epochs else aggregate.get("last_published_at") or aggregate.get("analyzed_at")
        aggregate["fetched_at"] = iso_from_epoch(fetched_epochs[0]) if fetched_epochs else aggregate.get("fetched_at") or aggregate.get("analyzed_at")
        aggregate["last_fetched_at"] = iso_from_epoch(fetched_epochs[-1]) if fetched_epochs else aggregate.get("last_fetched_at") or aggregate.get("analyzed_at")
        aggregate["published_time_label"] = aggregate["published_at"]
        aggregate["crawl_time_label"] = aggregate["fetched_at"]
        if history_points:
            latest_point = history_points[-1]
            previous_point = history_points[-2] if len(history_points) > 1 else None
            delta = int(latest_point.get("score") or 0) - int(previous_point.get("score") or 0) if previous_point else 0
            aggregate["trend_delta"] = delta
            if delta >= 5:
                aggregate["trend_label"] = "上升"
            elif delta <= -5:
                aggregate["trend_label"] = "下降"
            else:
                aggregate["trend_label"] = "平稳"
            aggregate["trend_points"] = history_points[-5:]
        else:
            aggregate["trend_delta"] = 0
            aggregate["trend_label"] = "平稳"
            aggregate["trend_points"] = []
        aggregate["reason"] = aggregate["reason"] or build_reason_text(aggregate, aggregate)
        aggregate["reason_points"] = list(dict.fromkeys([str(x).strip() for x in (aggregate.get("reason_points") or []) if str(x).strip()]))[:6]
        if not aggregate["reason_points"]:
            aggregate["reason_points"] = collect_reason_points(aggregate, aggregate)
        if not aggregate["raw_description"] and evidence_items:
            aggregate["raw_description"] = evidence_items[0].get("raw_description") or evidence_items[0].get("text") or ""
        if not aggregate["ai_summary"]:
            aggregate["ai_summary"] = short_summary(aggregate, {"text": aggregate.get("title") or ""})
        aggregate["summary"] = aggregate["ai_summary"]
        cards.append(aggregate)

    cards.sort(
        key=lambda x: (
            x["score"],
            x.get("source_count", 0),
            iso_to_epoch(x.get("last_seen_at")),
        ),
        reverse=True,
    )
    return cards[:50]


def build_dashboard():
    normalize_state_shape()
    latest = STATE.get("latest_result")
    results = []
    if latest:
        results.append(latest)
    results.extend(STATE.get("history") or [])
    cards = build_hotspot_cards(results)
    watch_terms = [str(x).strip() for x in STATE.get("manual_keywords", []) if str(x).strip()]
    active_query = (STATE.get("query") or "").strip()
    if active_query and active_query not in watch_terms:
        watch_terms.insert(0, active_query)
    today_prefix = now_iso()[:10]
    return {
        "brand": "HotPulse",
        "subtitle": "AI 热点雷达",
        "active_query": active_query,
        "watch_terms": watch_terms[:20],
        "source_options": [source["name"] for source in SOURCE_DEFS],
        "filter_defaults": {
            "sort": "score_desc",
            "levels": [],
            "sources": [],
            "search": "",
            "min_score": 0,
            "time_range": "all",
            "new_only": False,
            "resonance_only": False,
        },
        "stats": {
            "total_hotspots": len(cards),
            "today_new": len([c for c in cards if c.get("is_new")]),
            "urgent_hotspots": len([c for c in cards if c["level"] in ("HIGH", "URGENT")]),
            "watch_terms": len(watch_terms),
        },
        "hotspots": cards,
        "refresh_label": f"每 {max(1, POLL_SECONDS // 60)} 分钟自动更新",
        "last_checked_at": STATE.get("last_checked_at"),
        "last_error": STATE.get("last_error"),
    }


def run_analysis(manual=False):
    with STATE_LOCK:
        query = STATE.get("query", "").strip()
        if not query:
            terms = [str(x).strip() for x in STATE.get("manual_keywords", []) if str(x).strip()]
            query = " OR ".join(terms[:5])
        manual_inputs = dict(STATE.get("source_inputs", {}))
        settings = dict(STATE.get("settings", {}))
    if not query:
        raise RuntimeError("Please add a watch term or enter a search query.")
    items, errors = collect_source_items(query, manual_inputs)
    raw_source_counts = build_source_counts(items)
    scored_items, analysis_items = prepare_analysis_items(query, items)
    analysis_source_counts = build_source_counts(analysis_items)
    try:
        if OPENROUTER_API_KEY:
            result = openrouter_analyze(query, analysis_items, analysis_source_counts, raw_source_counts)
        else:
            result = heuristic_analyze(query, analysis_items, analysis_source_counts)
        result["mode"] = "openrouter" if OPENROUTER_API_KEY else "heuristic"
    except Exception as exc:
        result = heuristic_analyze(query, analysis_items, analysis_source_counts)
        result["mode"] = "fallback"
        result["fallback_error"] = str(exc)
    result["items"] = analysis_items[:80]
    result["raw_items"] = scored_items[:80]
    result["source_counts"] = analysis_source_counts
    result["raw_source_counts"] = raw_source_counts
    result["source_errors"] = errors
    result["analyzed_at"] = now_iso()
    result["query"] = query
    result["poll_seconds"] = POLL_SECONDS
    notify = int(result.get("hot_score") or 0) >= int(settings.get("push_threshold") or 70)
    with STATE_LOCK:
        STATE["latest_result"] = result
        STATE["last_checked_at"] = result["analyzed_at"]
        STATE["last_error"] = None
        STATE["history"].insert(0, result)
        STATE["history"] = STATE["history"][:20]
        if notify:
            notif = {
                "id": f"n-{int(time.time() * 1000)}",
                "title": f"Hotspot upshift: {result.get('headline', 'untitled')}",
                "body": f"{result.get('hot_level', 'low').upper()} / {result.get('hot_score', 0)} score, sources {len(analysis_source_counts)}",
                "created_at": now_iso(),
                "kind": "hotspot",
            }
            STATE["notifications"].insert(0, notif)
            STATE["notifications"] = STATE["notifications"][:30]
            broadcast({"type": "notification", "data": notif})
            if settings.get("email_enabled"):
                subject = notif["title"]
                body = json.dumps(result, ensure_ascii=False, indent=2)
                try:
                    send_email(subject, body)
                except Exception as exc:
                    STATE["last_error"] = f"email: {exc}"
        save_state()
    broadcast({"type": "result", "data": result})
    return result

def scheduler_loop():
    while True:
        try:
            time.sleep(POLL_SECONDS)
            with STATE_LOCK:
                query = (STATE.get("query") or "").strip()
            if query:
                run_analysis(manual=False)
        except Exception as exc:
            with STATE_LOCK:
                STATE["last_error"] = str(exc)
                save_state()
            broadcast({"type": "error", "data": {"message": str(exc)}})


class Handler(BaseHTTPRequestHandler):
    server_version = "HotMonitor/1.0"

    def _send_json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _serve_static(self, filename):
        path = WEB_DIR / filename
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = path.read_bytes()
        content_type = "text/plain; charset=utf-8"
        if filename.endswith(".html"):
            content_type = "text/html; charset=utf-8"
        elif filename.endswith(".css"):
            content_type = "text/css; charset=utf-8"
        elif filename.endswith(".js"):
            content_type = "application/javascript; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._serve_static("index.html")
        if self.path == "/styles.css":
            return self._serve_static("styles.css")
        if self.path == "/app.js":
            return self._serve_static("app.js")
        if self.path == "/api/state":
            with STATE_LOCK:
                return self._send_json({
                    "sources": SOURCE_DEFS,
                    "state": STATE,
                    "dashboard": build_dashboard(),
                    "openrouter_ready": bool(OPENROUTER_API_KEY),
                    "twitterapi_ready": bool(TWITTERAPI_KEY),
                    "poll_seconds": POLL_SECONDS,
                })
        if self.path == "/api/run":
            try:
                result = run_analysis(manual=True)
                return self._send_json({"ok": True, "result": result})
            except Exception as exc:
                with STATE_LOCK:
                    STATE["last_error"] = str(exc)
                    save_state()
                return self._send_json({"ok": False, "error": str(exc)}, 400)
        if self.path == "/api/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q = queue.Queue()
            EVENTS.append(q)
            try:
                self.wfile.write(b"event: hello\ndata: {}\n\n")
                self.wfile.flush()
                while True:
                    try:
                        event = q.get(timeout=25)
                        payload = json.dumps(event, ensure_ascii=False)
                        self.wfile.write(f"event: {event['type']}\ndata: {payload}\n\n".encode("utf-8"))
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except Exception:
                pass
            finally:
                if q in EVENTS:
                    EVENTS.remove(q)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if self.path == "/api/config":
            try:
                body = self._read_json()
                with STATE_LOCK:
                    if "query" in body:
                        STATE["query"] = (body.get("query") or "").strip()
                    if isinstance(body.get("source_inputs"), dict):
                        for key, value in body["source_inputs"].items():
                            if key in STATE["source_inputs"]:
                                STATE["source_inputs"][key] = value or ""
                    if isinstance(body.get("settings"), dict):
                        STATE["settings"].update(body["settings"])
                    if isinstance(body.get("manual_keywords"), list):
                        STATE["manual_keywords"] = [
                            str(x).strip()
                            for x in body["manual_keywords"][:20]
                            if str(x).strip()
                        ]
                    if isinstance(body.get("watch_terms"), list):
                        STATE["manual_keywords"] = [
                            str(x).strip()
                            for x in body["watch_terms"][:20]
                            if str(x).strip()
                        ]
                    save_state()
                return self._send_json({"ok": True})
            except Exception as exc:
                return self._send_json({"ok": False, "error": str(exc)}, 400)
        self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, fmt, *args):
        return


def main():
    ensure_dirs()
    save_state()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", DEFAULT_PORT), Handler)
    print(f"Hot Monitor running on http://127.0.0.1:{DEFAULT_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
