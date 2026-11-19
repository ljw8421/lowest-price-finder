"""검색: 소스 호출, 캐시, 필터링, 정렬."""
import asyncio
import statistics
import time

import httpx

from .config import settings
from .sources import coupang_search_url, search_coupang, search_demo, search_naver

RESULT_LIMIT = 10
REQUEST_TIMEOUT = 8.0
SORT_OPTIONS = ("price", "relevance")

ACCESSORY_WORDS = ["케이스", "커버", "필름", "보호필름", "거치대", "스트랩",
                   "파우치", "충전기", "케이블", "젠더", "스킨", "호환"]
# 중앙값의 이 비율보다 싼 상품은 다른 상품일 가능성이 높다고 본다.
MEDIAN_PRICE_RATIO = 0.35
MEDIAN_MIN_ITEMS = 4

# 검색어 -> (저장 시각, 필터링 전 상품 목록). 같은 검색어는 API를 다시 부르지 않는다.
_cache: dict[str, tuple[float, list[dict]]] = {}


def clear_cache() -> None:
    _cache.clear()


# --------------------------------------------------------- 필터·정렬 ----
def filter_accessories(query: str, items: list[dict]) -> tuple[list[dict], int]:
    """액세서리와 지나치게 싼 상품을 걸러낸다. (남은 상품, 제외한 개수)를 돌려준다."""
    if not items:
        return items, 0
    q = query.lower()
    allowed = {w for w in ACCESSORY_WORDS if w in q}  # 검색어에 있는 단어는 허용
    blocked = [w for w in ACCESSORY_WORDS if w not in allowed]
    kept = [it for it in items if not any(w in it["title"].lower() for w in blocked)]
    if len(kept) >= MEDIAN_MIN_ITEMS:
        median = statistics.median(it["price"] for it in kept)
        kept = [it for it in kept if it["price"] >= median * MEDIAN_PRICE_RATIO]
    return kept, len(items) - len(kept)


def dedupe(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in items:
        key = (it["mall"], it["title"], it["price"])
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def sort_items(items: list[dict], sort: str) -> list[dict]:
    if sort == "relevance":
        # 소스 안에서의 순위대로. 순위가 같으면 원래 순서(네이버 먼저)를 유지한다.
        return sorted(items, key=lambda it: it["rank"])
    return sorted(items, key=lambda it: it["price"])


def normalize_sort(sort: str | None) -> str:
    return sort if sort in SORT_OPTIONS else "price"


# --------------------------------------------------------- 소스 호출 ----
STATUS_HINTS = {
    401: "인증 실패: .env의 API 키를 확인하세요",
    403: "권한 없음: 네이버 개발자센터 > 내 애플리케이션 > API 설정에서 '검색'이 선택돼 있는지 확인하세요",
    429: "호출 한도 초과",
}


def describe_error(exc: BaseException) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        try:  # 네이버는 {"errorMessage": ..., "errorCode": ...} 형태로 오류를 준다
            body = exc.response.json()
            detail = body.get("errorMessage") or body.get("message") or ""
        except (ValueError, AttributeError):
            detail = ""
        parts = [f"HTTP {code}", STATUS_HINTS.get(code, ""), detail]
        return " · ".join(p for p in parts if p)
    if isinstance(exc, httpx.TimeoutException):
        return "응답 시간 초과"
    return f"{type(exc).__name__}: {exc}"


async def fetch_all(query: str) -> tuple[list[dict], dict[str, str]]:
    """설정된 소스를 동시에 호출한다. 한 곳이 실패해도 나머지 결과는 돌려준다."""
    if settings.demo_mode:
        return search_demo(query), {}

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        tasks = {}
        if settings.naver_enabled:
            tasks["naver"] = search_naver(client, query)
        if settings.coupang_enabled:
            tasks["coupang"] = search_coupang(client, query)
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    items: list[dict] = []
    errors: dict[str, str] = {}
    for name, result in zip(tasks, results):
        if isinstance(result, BaseException):
            errors[name] = describe_error(result)
        else:
            items.extend(result)
    return items, errors


async def _fetch_cached(query: str) -> tuple[list[dict], dict[str, str]]:
    hit = _cache.get(query)
    if hit and time.monotonic() - hit[0] < settings.cache_seconds:
        return hit[1], {}
    items, errors = await fetch_all(query)
    if not errors:  # 일부 실패한 결과는 저장하지 않는다
        _cache[query] = (time.monotonic(), items)
    return items, errors


# --------------------------------------------------------- 검색 ----
async def search(query: str, strict: bool = True, sort: str = "price") -> dict:
    query = query.strip()[:100]
    sort = normalize_sort(sort)
    items, errors = await _fetch_cached(query)

    items = dedupe(items)
    removed = 0
    if strict:
        items, removed = filter_accessories(query, items)

    return {
        "query": query,
        "sort": sort,
        "strict": strict,
        "demo": settings.demo_mode,
        "count": len(items),
        "filtered_out": removed,
        "cheapest": min(items, key=lambda it: it["price"], default=None),
        "items": sort_items(items, sort)[:RESULT_LIMIT],
        "errors": errors,
        "sources": {
            "naver": settings.naver_enabled,
            "coupang": settings.coupang_enabled,
        },
        "coupang_search_url": coupang_search_url(query),
    }
