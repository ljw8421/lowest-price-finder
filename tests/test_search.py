import asyncio

from fastapi.testclient import TestClient

from app import search as search_module
from app.main import app
from app.search import RESULT_LIMIT, dedupe, filter_accessories, search, sort_items
from app.sources import parse_coupang, parse_naver
from tests.conftest import make_item


# --------------------------------------------------------- 네이버 파싱 ----
def test_parse_naver_keeps_only_new_products():
    data = {"items": [
        {"title": "<b>에어팟</b> 프로", "lprice": "250000", "productType": "1", "mallName": "네이버"},
        {"title": "에어팟 일반", "lprice": "260000", "productType": "2", "mallName": "11번가"},
        {"title": "에어팟 중고", "lprice": "100000", "productType": "4", "mallName": "중고나라"},
        {"title": "에어팟 단종", "lprice": "90000", "productType": "7", "mallName": "A"},
        {"title": "에어팟 판매예정", "lprice": "80000", "productType": "10", "mallName": "B"},
        {"title": "가격 없음", "lprice": "", "productType": "2", "mallName": "C"},
    ]}
    items = parse_naver(data)
    assert [it["title"] for it in items] == ["에어팟 프로", "에어팟 일반"]
    assert items[0]["mall"] == "네이버 가격비교"
    assert items[0]["badge"] == "여러 판매처 비교"
    assert items[1]["mall"] == "11번가"
    assert [it["rank"] for it in items] == [0, 1]


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


def test_dedupe():
    items = [make_item(1000, "A", "몰"), make_item(1000, "A", "몰"), make_item(1000, "A", "다른몰")]
    assert len(dedupe(items)) == 2


# --------------------------------------------------------- 정렬 ----
def test_sort_by_price_and_relevance():
    items = [make_item(300, rank=0), make_item(100, rank=2), make_item(200, rank=1)]
    assert [it["price"] for it in sort_items(items, "price")] == [100, 200, 300]
    assert [it["rank"] for it in sort_items(items, "relevance")] == [0, 1, 2]


def _fake_fetch(items, calls):
    async def fake(query):
        calls.append(query)
        return items, {}
    return fake


def test_search_limits_to_10_and_finds_cheapest(monkeypatch):
    items = [make_item(100000 + i * 1000, f"상품 {i}", rank=i) for i in range(30)]
    calls = []
    monkeypatch.setattr(search_module, "fetch_all", _fake_fetch(items, calls))

    result = asyncio.run(search("상품", strict=False, sort="price"))
    assert len(result["items"]) == RESULT_LIMIT
    assert result["count"] == 30
    assert result["cheapest"]["price"] == 100000
    assert [it["price"] for it in result["items"]] == sorted(it["price"] for it in result["items"])


def test_cheapest_is_independent_of_sort(monkeypatch):
    items = [make_item(300, "a", rank=0), make_item(100, "b", rank=1)]
    monkeypatch.setattr(search_module, "fetch_all", _fake_fetch(items, []))
    result = asyncio.run(search("x", strict=False, sort="relevance"))
    assert result["items"][0]["price"] == 300
    assert result["cheapest"]["price"] == 100


def test_search_uses_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(search_module, "fetch_all", _fake_fetch([make_item(1000)], calls))
    asyncio.run(search("상품"))
    asyncio.run(search("상품", strict=False, sort="relevance"))
    assert calls == ["상품"]


def test_failed_results_are_not_cached(monkeypatch):
    calls = []

    async def failing(query):
        calls.append(query)
        return [], {"naver": "HTTP 500"}

    monkeypatch.setattr(search_module, "fetch_all", failing)
    asyncio.run(search("상품"))
    result = asyncio.run(search("상품"))
    assert len(calls) == 2
    assert result["errors"] == {"naver": "HTTP 500"}


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
