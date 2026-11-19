"""가격 데이터 소스: 11번가 Open API, 쿠팡 파트너스 API, 데모 데이터.

모든 소스는 같은 모양의 상품 dict 목록을 돌려준다.
    source, title, price, mall, link, image, brand, badge, rank
rank 는 소스가 돌려준 순서(관련도순)이며, 관련도순 정렬에 쓴다.

네이버 쇼핑 검색 API는 2026-07-31에 종료되어 제거했다 (CLAUDE.md 참고).
"""
import hashlib
import hmac
import html
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

import httpx

from .config import settings

# ---------------------------------------------------------------- 공통 ----


def clean_title(text: str | None) -> str:
    """태그와 HTML 엔티티를 없앤다."""
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def _to_price(value) -> int:
    try:
        return int(str(value or "0").replace(",", "").strip() or 0)
    except (TypeError, ValueError):
        return 0


class SourceError(Exception):
    """API가 HTTP 200으로 오류 내용을 돌려줄 때 쓴다 (11번가)."""


# --------------------------------------------------------- 11번가 ----
ELEVENST_URL = "https://openapi.11st.co.kr/openapi/OpenApiService.tmall"
ELEVENST_FETCH_SIZE = 100  # 관련도(인기도)순 상위 100건을 받아서 그 안에서 가격순으로 정렬한다
ELEVENST_ERROR_HINTS = {
    "003": "등록되지 않은 키입니다. .env의 ELEVENST_API_KEY를 확인하세요",
    "004": "하루 호출 한도를 넘었습니다",
    "005": "접근이 거부되었습니다. 키가 만료됐을 수 있습니다 (180일마다 갱신 필요)",
    "013": "잘못된 키 형식입니다. .env의 ELEVENST_API_KEY를 확인하세요",
}


def _text(node: ET.Element, *names: str) -> str:
    """가이드 예제와 필드 표의 태그 이름이 달라서, 여러 이름 중 처음 찾은 값을 쓴다."""
    for name in names:
        found = node.find(name)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return ""


def _decode_xml(content: bytes) -> ET.Element:
    # 응답은 EUC-KR이다. expat은 EUC-KR을 직접 못 읽으므로 먼저 문자열로 바꾼다.
    text = content.decode("cp949", errors="replace")
    text = re.sub(r"^<\?xml[^>]*\?>", "", text.lstrip())
    return ET.fromstring(text)


def parse_elevenst(content: bytes) -> list[dict]:
    root = _decode_xml(content)
    if root.tag == "ErrorResponse":
        code = _text(root, "ErrorCode")
        detail = _text(root, "ErrorDetail") or _text(root, "ErrorMessage")
        hint = ELEVENST_ERROR_HINTS.get(code, "")
        raise SourceError(" · ".join(p for p in (f"오류 {code}", hint, detail) if p))

    results = []
    for rank, product in enumerate(root.iter("Product")):
        list_price = _to_price(_text(product, "ProductPrice"))
        sale_price = _to_price(_text(product, "SalePrice"))  # 할인모음가
        # 할인모음가가 있으면 그 값을, 없으면 판매가를 쓴다.
        price = sale_price if sale_price > 0 else list_price
        if price <= 0:
            continue
        delivery = _text(product, "Delivery")
        results.append({
            "source": "elevenst",
            "title": clean_title(_text(product, "ProductName")),
            "price": price,
            "mall": "11번가",
            "link": _text(product, "DetailPageUrl", "ProductDetailUrl"),
            "image": _text(product, "ProductImage300", "ProductImage", "ImageUrl"),
            "brand": "",
            "badge": f"배송 {delivery}" if delivery else "",
            "seller": _text(product, "Seller"),
            "rank": rank,
        })
    return results


async def search_elevenst(client: httpx.AsyncClient, query: str) -> list[dict]:
    resp = await client.get(ELEVENST_URL, params={
        "key": settings.elevenst_api_key,
        "apiCode": "ProductSearch",
        "keyword": query,
        "pageNum": 1,
        "pageSize": ELEVENST_FETCH_SIZE,
        "sortCd": "CP",  # 인기도순
    })
    resp.raise_for_status()
    return parse_elevenst(resp.content)


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


# --------------------------------------------------------- 바로가기 링크 ----
def shortcut_links(query: str) -> list[dict]:
    """API로 가격을 가져올 수 없는 곳은 같은 검색어의 검색 결과로 가는 링크만 준다."""
    q = urllib.parse.quote(query)
    return [
        {"name": "네이버 쇼핑", "source": "naver",
         "url": f"https://search.shopping.naver.com/search/all?query={q}"},
        {"name": "쿠팡", "source": "coupang",
         "url": f"https://www.coupang.com/np/search?q={q}"},
    ]


# --------------------------------------------------------- 데모 데이터 ----
DEMO_PRICES = [1.00, 0.97, 1.03, 0.99, 1.05, 1.01, 1.08]


def search_demo(query: str) -> list[dict]:
    base = 50000 + (sum(map(ord, query)) % 50) * 10000
    link = "https://search.11st.co.kr/Search.tmall?kwd=" + urllib.parse.quote(query)
    items = [{
        "source": "elevenst",
        "title": f"{query} (데모 상품 {rank + 1})",
        "price": int(round(base * ratio, -2)),
        "mall": "11번가",
        "link": f"{link}&demo={rank + 1}",  # 중복 제거가 링크 기준이라 상품마다 다르게
        "image": "",
        "brand": "",
        "badge": "배송 무료" if rank % 2 == 0 else "",
        "seller": f"데모판매자{rank + 1}",
        "rank": rank,
    } for rank, ratio in enumerate(DEMO_PRICES)]
    # 액세서리처럼 보이는 싼 상품 (필터 동작 확인용)
    items.append({**items[0], "title": f"{query} 전용 케이스 (데모)", "price": 9900,
                  "link": f"{link}&demo=case", "rank": len(items)})
    return items
