"""가격 데이터 소스: 네이버 쇼핑 검색 API, 쿠팡 파트너스 API, 데모 데이터.

모든 소스는 같은 모양의 상품 dict 목록을 돌려준다.
    source, title, price, mall, link, image, brand, badge, rank
rank 는 소스가 돌려준 순서(관련도순)이며, 관련도순 정렬에 쓴다.
"""
import hashlib
import hmac
import html
import re
import time
import urllib.parse

import httpx

from .config import settings

# ---------------------------------------------------------------- 공통 ----


def clean_title(text: str | None) -> str:
    """네이버 결과의 <b> 태그와 HTML 엔티티를 없앤다."""
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def _to_price(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------- 네이버 쇼핑 ----
NAVER_URL = "https://openapi.naver.com/v1/search/shop.json"
NAVER_FETCH_SIZE = 100  # 정확도순 상위 100건을 받아서 그 안에서 가격순으로 정렬한다
# productType: 1~3 = 일반 상품, 4~6 = 중고, 7~9 = 단종, 10~12 = 판매예정
NAVER_NEW_TYPES = {"1", "2", "3"}
NAVER_CATALOG_TYPE = "1"  # 여러 판매처를 묶은 네이버 가격비교 카탈로그


def parse_naver(data: dict) -> list[dict]:
    results = []
    for rank, item in enumerate(data.get("items") or []):
        product_type = str(item.get("productType"))
        if product_type not in NAVER_NEW_TYPES:
            continue  # 중고, 단종, 판매예정 제외
        price = _to_price(item.get("lprice"))
        if price <= 0:
            continue
        is_catalog = product_type == NAVER_CATALOG_TYPE
        results.append({
            "source": "naver",
            "title": clean_title(item.get("title")),
            "price": price,
            "mall": "네이버 가격비교" if is_catalog else (item.get("mallName") or "네이버"),
            "link": item.get("link") or "",
            "image": item.get("image") or "",
            "brand": item.get("brand") or item.get("maker") or "",
            "badge": "여러 판매처 비교" if is_catalog else "",
            "rank": rank,
        })
    return results


async def search_naver(client: httpx.AsyncClient, query: str) -> list[dict]:
    resp = await client.get(
        NAVER_URL,
        params={"query": query, "display": NAVER_FETCH_SIZE, "sort": "sim"},
        headers={
            "X-Naver-Client-Id": settings.naver_client_id,
            "X-Naver-Client-Secret": settings.naver_client_secret,
        },
    )
    resp.raise_for_status()
    return parse_naver(resp.json())


# --------------------------------------------------------- 쿠팡 파트너스 ----
COUPANG_HOST = "https://api-gateway.coupang.com"
COUPANG_PATH = "/v2/providers/affiliate_open_api/apis/openapi/products/search"
COUPANG_FETCH_SIZE = 10


def coupang_auth_header(method: str, path: str, query: str) -> str:
    signed_date = time.strftime("%y%m%dT%H%M%SZ", time.gmtime())
    message = signed_date + method + path + query
    signature = hmac.new(
        settings.coupang_secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return (
        f"CEA algorithm=HmacSHA256, access-key={settings.coupang_access_key}, "
        f"signed-date={signed_date}, signature={signature}"
    )


def parse_coupang(data: dict) -> list[dict]:
    results = []
    products = (data.get("data") or {}).get("productData") or []
    for rank, item in enumerate(products):
        price = _to_price(item.get("productPrice"))
        if price <= 0:
            continue
        results.append({
            "source": "coupang",
            "title": clean_title(item.get("productName")),
            "price": price,
            "mall": "쿠팡",
            "link": item.get("productUrl") or "",
            "image": item.get("productImage") or "",
            "brand": "",
            "badge": "로켓배송" if item.get("isRocket") else "",
            "rank": rank,
        })
    return results


async def search_coupang(client: httpx.AsyncClient, query: str) -> list[dict]:
    # 서명에 쓴 쿼리 문자열과 실제 요청의 쿼리 문자열이 똑같아야 한다.
    qs = urllib.parse.urlencode({"keyword": query, "limit": COUPANG_FETCH_SIZE})
    resp = await client.get(
        f"{COUPANG_HOST}{COUPANG_PATH}?{qs}",
        headers={
            "Authorization": coupang_auth_header("GET", COUPANG_PATH, qs),
            "Content-Type": "application/json;charset=UTF-8",
        },
    )
    resp.raise_for_status()
    return parse_coupang(resp.json())


def coupang_search_url(query: str) -> str:
    """쿠팡 API 키가 없을 때 직접 확인해 볼 수 있는 쿠팡 검색 링크."""
    return "https://www.coupang.com/np/search?q=" + urllib.parse.quote(query)


# --------------------------------------------------------- 데모 데이터 ----
DEMO_MALLS = [
    ("네이버 가격비교", "naver", 1.00, "여러 판매처 비교"),
    ("쿠팡", "coupang", 0.97, "로켓배송"),
    ("11번가", "naver", 1.03, ""),
    ("G마켓", "naver", 0.99, ""),
    ("SSG.COM", "naver", 1.05, ""),
    ("옥션", "naver", 1.01, ""),
    ("롯데ON", "naver", 1.08, ""),
]


def search_demo(query: str) -> list[dict]:
    base = 50000 + (sum(map(ord, query)) % 50) * 10000
    link = "https://search.shopping.naver.com/search/all?query=" + urllib.parse.quote(query)
    items = [{
        "source": source,
        "title": f"{query} (데모 상품)",
        "price": int(round(base * ratio, -2)),
        "mall": mall,
        "link": link,
        "image": "",
        "brand": "",
        "badge": badge,
        "rank": rank,
    } for rank, (mall, source, ratio, badge) in enumerate(DEMO_MALLS)]
    # 액세서리처럼 보이는 싼 상품 (필터 동작 확인용)
    items.append({**items[0], "title": f"{query} 전용 케이스 (데모)", "price": 9900,
                  "mall": "스마트스토어", "badge": "", "rank": len(items)})
    return items
