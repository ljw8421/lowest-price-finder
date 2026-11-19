import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app import search as search_module
from app.config import settings
from app.main import app
from app.search import (RESULT_LIMIT, dedupe, describe_error, filter_accessories,
                        search, sort_items)
from app.sources import (SourceError, parse_coupang, parse_elevenst, search_elevenst,
                         shortcut_links)
from tests.conftest import make_item

ELEVENST_OK = """<?xml version="1.0" encoding="EUC-KR"?>
<ProductSearchResponse>
  <Request><ProcessingTime>0.1 sec</ProcessingTime></Request>
  <Products>
    <TotalCount>3</TotalCount>
    <Product>
      <ProductCode>101</ProductCode>
      <ProductName><![CDATA[애플 에어팟 프로 3]]></ProductName>
      <ProductPrice>359000</ProductPrice>
      <SalePrice>329000</SalePrice>
      <ProductImage>https://image.11st.co.kr/101.jpg</ProductImage>
      <Seller>애플공식</Seller>
      <DetailPageUrl>https://www.11st.co.kr/products/101</DetailPageUrl>
      <Delivery>무료</Delivery>
    </Product>
    <Product>
      <ProductCode>102</ProductCode>
      <ProductName>에어팟 프로 3 &amp; 케이스</ProductName>
      <ProductPrice>340000</ProductPrice>
      <SalePrice>0</SalePrice>
      <ImageUrl>https://image.11st.co.kr/102.jpg</ImageUrl>
      <ProductDetailUrl>https://www.11st.co.kr/products/102</ProductDetailUrl>
    </Product>
    <Product>
      <ProductCode>103</ProductCode>
      <ProductName>가격 없음</ProductName>
      <ProductPrice></ProductPrice>
    </Product>
  </Products>
</ProductSearchResponse>""".encode("cp949")

ELEVENST_ERROR = ('<?xml version="1.0" encoding="EUC-KR"?><ErrorResponse><ErrorCode>003</ErrorCode>'
                  '<ErrorMessage>tMall.unregisteredKey</ErrorMessage>'
                  '<ErrorDetail>등록되지 않은  OpenAPI Key입니다. key 파라메터를 확인해 주세요.</ErrorDetail>'
                  '</ErrorResponse>').encode("cp949")


# --------------------------------------------------------- 11번가 파싱 ----
def test_parse_elevenst():
    items = parse_elevenst(ELEVENST_OK)
    assert [it["title"] for it in items] == ["애플 에어팟 프로 3", "에어팟 프로 3 & 케이스"]
    first, second = items
    assert first["price"] == 329000  # 할인모음가 우선
    assert second["price"] == 340000  # 할인모음가가 0이면 판매가
    assert first["link"] == "https://www.11st.co.kr/products/101"
    assert second["link"] == "https://www.11st.co.kr/products/102"  # 필드 표의 태그 이름도 읽음
    assert second["image"] == "https://image.11st.co.kr/102.jpg"
    assert first["badge"] == "배송 무료"
    assert first["seller"] == "애플공식"
    assert first["mall"] == "11번가"
    assert [it["rank"] for it in items] == [0, 1]


def test_parse_elevenst_error_response():
    with pytest.raises(SourceError) as e:
        parse_elevenst(ELEVENST_ERROR)
    msg = str(e.value)
    assert msg.startswith("오류 003")
    assert "ELEVENST_API_KEY" in msg
    assert "등록되지 않은" in msg


def test_elevenst_request_format(monkeypatch):
    monkeypatch.setattr(settings, "elevenst_api_key", "k" * 32)
    seen = {}

    def handler(request):
        seen["url"] = request.url
        return httpx.Response(200, content=ELEVENST_OK)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await search_elevenst(client, "에어팟 프로")

    items = asyncio.run(run())
    assert len(items) == 2
    assert seen["url"].scheme == "https"
    assert seen["url"].host == "openapi.11st.co.kr"
    assert seen["url"].path == "/openapi/OpenApiService.tmall"
    assert dict(seen["url"].params) == {
        "key": "k" * 32, "apiCode": "ProductSearch", "keyword": "에어팟 프로",
        "pageNum": "1", "pageSize": "100", "sortCd": "CP"}


def test_parse_coupang():
    data = {"data": {"productData": [
        {"productName": "에어팟", "productPrice": 240000, "productUrl": "https://c.com/1", "isRocket": True},
        {"productName": "가격 없음", "productPrice": None},
    ]}}
    items = parse_coupang(data)
    assert len(items) == 1
    assert items[0]["mall"] == "쿠팡"
    assert items[0]["badge"] == "로켓배송"


# --------------------------------------------------------- 필터 ----
def test_filter_removes_accessories():
    items = [make_item(250000, "에어팟 프로"), make_item(3000, "에어팟 프로 실리콘 케이스")]
    kept, removed = filter_accessories("에어팟 프로", items)
    assert [it["title"] for it in kept] == ["에어팟 프로"]
    assert removed == 1


def test_filter_allows_accessory_words_in_query():
    items = [make_item(15000, "에어팟 프로 케이스"), make_item(12000, "에어팟 프로 케이스 투명")]
    kept, removed = filter_accessories("에어팟 프로 케이스", items)
    assert len(kept) == 2 and removed == 0


def test_filter_removes_suspiciously_cheap_items():
    items = [make_item(p, f"상품{p}") for p in (100000, 105000, 110000, 98000, 20000)]
    kept, removed = filter_accessories("상품", items)
    assert 20000 not in [it["price"] for it in kept]
    assert removed == 1


def test_dedupe_by_link():
    a = make_item(1000, "A")
    b = {**make_item(1000, "A"), "link": "https://example.com/other"}
    assert len(dedupe([a, dict(a), b])) == 2


# --------------------------------------------------------- 정렬 ----
def test_sort_by_price_and_relevance():
    items = [make_item(300, rank=0), make_item(100, rank=2), make_item(200, rank=1)]
    assert [it["price"] for it in sort_items(items, "price")] == [100, 200, 300]
    assert [it["rank"] for it in sort_items(items, "relevance")] == [0, 1, 2]


def _fake_fetch(items, calls, errors=None):
    async def fake(query):
        calls.append(query)
        return items, dict(errors or {})
    return fake


def _unique(n, start=100000):
    return [{**make_item(start + i * 1000, f"상품 {i}", rank=i), "link": f"https://e.com/{i}"}
            for i in range(n)]


def test_search_limits_to_10_and_finds_cheapest(monkeypatch):
    monkeypatch.setattr(search_module, "fetch_all", _fake_fetch(_unique(30), []))
    result = asyncio.run(search("상품", strict=False, sort="price"))
    assert len(result["items"]) == RESULT_LIMIT
    assert result["count"] == 30
    assert result["cheapest"]["price"] == 100000
    assert [it["price"] for it in result["items"]] == sorted(it["price"] for it in result["items"])


def test_cheapest_is_independent_of_sort(monkeypatch):
    items = [{**make_item(300, "a", rank=0), "link": "https://e.com/a"},
             {**make_item(100, "b", rank=1), "link": "https://e.com/b"}]
    monkeypatch.setattr(search_module, "fetch_all", _fake_fetch(items, []))
    result = asyncio.run(search("x", strict=False, sort="relevance"))
    assert result["items"][0]["price"] == 300
    assert result["cheapest"]["price"] == 100


def test_results_are_not_cached(monkeypatch):
    """11번가 약관(데이터 저장 금지) 때문에 매 검색마다 API를 호출한다."""
    calls = []
    monkeypatch.setattr(search_module, "fetch_all", _fake_fetch(_unique(1), calls))
    asyncio.run(search("상품"))
    asyncio.run(search("상품"))
    assert calls == ["상품", "상품"]


def test_errors_use_display_names(monkeypatch):
    monkeypatch.setattr(search_module, "fetch_all", _fake_fetch([], [], {"elevenst": "오류 003"}))
    result = asyncio.run(search("상품"))
    assert result["errors"] == {"11번가": "오류 003"}


def test_shortcuts_exclude_connected_sources(monkeypatch):
    monkeypatch.setattr(search_module, "fetch_all", _fake_fetch([], []))
    names = [s["name"] for s in asyncio.run(search("상품"))["shortcuts"]]
    assert names == ["네이버 쇼핑", "쿠팡"]
    monkeypatch.setattr(settings, "coupang_access_key", "a")
    monkeypatch.setattr(settings, "coupang_secret_key", "b")
    names = [s["name"] for s in asyncio.run(search("상품"))["shortcuts"]]
    assert names == ["네이버 쇼핑"]


def test_shortcut_urls_encode_query():
    urls = {s["name"]: s["url"] for s in shortcut_links("에어팟 프로")}
    assert urls["네이버 쇼핑"].endswith("query=%EC%97%90%EC%96%B4%ED%8C%9F%20%ED%94%84%EB%A1%9C")


# --------------------------------------------------------- 오류 메시지 ----
def test_describe_error_passes_source_error_through():
    assert describe_error(SourceError("오류 004 · 하루 호출 한도를 넘었습니다")).startswith("오류 004")


def test_describe_error_http_status():
    request = httpx.Request("GET", "https://example.com")
    exc = httpx.HTTPStatusError("e", request=request, response=httpx.Response(401, request=request))
    assert describe_error(exc).startswith("HTTP 401")


def test_describe_error_timeout():
    assert describe_error(httpx.ReadTimeout("t")) == "응답 시간 초과"


# --------------------------------------------------------- 웹 화면·API ----
client = TestClient(app)


def test_home_page_has_filter_checked_by_default():
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'name="strict" value="1" checked' in resp.text
    assert "최저가 ·" not in resp.text


def test_search_page_in_demo_mode():
    resp = client.get("/", params={"q": "에어팟", "strict": "1"})
    assert resp.status_code == 200
    assert "데모 데이터" in resp.text
    assert "최저가 ·" in resp.text
    assert "전용 케이스" not in resp.text  # 액세서리 필터 켜짐
    assert "네이버 쇼핑에서 직접 확인하기" in resp.text


def test_unchecked_filter_shows_accessories():
    resp = client.get("/", params={"q": "에어팟"})  # 체크 해제 시 strict 값이 오지 않음
    assert "전용 케이스" in resp.text
    assert 'name="strict" value="1" checked' not in resp.text


def test_search_page_escapes_query():
    resp = client.get("/", params={"q": "<script>alert(1)</script>"})
    assert "<script>alert(1)</script>" not in resp.text


def test_api_search():
    resp = client.get("/api/search", params={"q": "에어팟"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["demo"] is True
    assert data["strict"] is True
    assert len(data["items"]) <= RESULT_LIMIT


def test_api_search_requires_query():
    assert client.get("/api/search", params={"q": "  "}).status_code == 400
    assert client.get("/api/search").status_code == 422
