"""
최저가 비교 서버 (Python 표준 라이브러리만 사용 — 설치 불필요)

실행:  python server.py
접속:  http://localhost:8000

API 키는 같은 폴더의 .env 파일에 넣으세요 (.env.example 참고).
키가 하나도 없으면 데모(가짜) 데이터로 동작합니다.
"""
import hashlib
import hmac
import html
import json
import os
import re
import statistics
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------- 설정 ----
def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env(BASE_DIR / ".env")

NAVER_ID = os.getenv("NAVER_CLIENT_ID", "")
NAVER_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")
COUPANG_ACCESS = os.getenv("COUPANG_ACCESS_KEY", "")
COUPANG_SECRET = os.getenv("COUPANG_SECRET_KEY", "")
PORT = int(os.getenv("PORT", "8000"))
CACHE_SECONDS = int(os.getenv("CACHE_SECONDS", "600"))

DEMO_MODE = not (NAVER_ID and NAVER_SECRET) and not (COUPANG_ACCESS and COUPANG_SECRET)

# 같은 검색어는 일정 시간 캐시 (API 호출 한도 절약)
_cache: dict[str, tuple[float, dict]] = {}


# --------------------------------------------------------- 공통 유틸 ----
def clean_title(text: str) -> str:
    """네이버 결과의 <b> 태그, HTML 엔티티 제거"""
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def http_get_json(url: str, headers: dict, timeout: int = 8) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# --------------------------------------------------------- 네이버 쇼핑 ----
# productType: 1~3 = 일반 상품, 4~6 = 중고, 7~9 = 단종, 10~12 = 판매예정
NAVER_NEW_TYPES = {"1", "2", "3"}


def search_naver(query: str) -> list[dict]:
    if not (NAVER_ID and NAVER_SECRET):
        return []
    params = urllib.parse.urlencode({"query": query, "display": 100, "sort": "sim"})
    data = http_get_json(
        f"https://openapi.naver.com/v1/search/shop.json?{params}",
        {"X-Naver-Client-Id": NAVER_ID, "X-Naver-Client-Secret": NAVER_SECRET},
    )
    results = []
    for item in data.get("items", []):
        if str(item.get("productType")) not in NAVER_NEW_TYPES:
            continue  # 중고·단종·판매예정 제외
        try:
            price = int(item.get("lprice") or 0)
        except ValueError:
            continue
        if price <= 0:
            continue
        mall = item.get("mallName") or "네이버"
        is_catalog = str(item.get("productType")) == "1"
        results.append({
            "source": "naver",
            "title": clean_title(item.get("title")),
            "price": price,
            "mall": "네이버 가격비교" if is_catalog else mall,
            "link": item.get("link"),
            "image": item.get("image"),
            "brand": item.get("brand") or item.get("maker") or "",
            "badge": "여러 판매처 비교" if is_catalog else "",
        })
    return results


# --------------------------------------------------------- 쿠팡 파트너스 ----
COUPANG_HOST = "https://api-gateway.coupang.com"
COUPANG_PATH = "/v2/providers/affiliate_open_api/apis/openapi/products/search"


def coupang_auth_header(method: str, path: str, query: str) -> str:
    signed_date = time.strftime("%y%m%dT%H%M%SZ", time.gmtime())
    message = signed_date + method + path + query
    signature = hmac.new(
        COUPANG_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return (
        f"CEA algorithm=HmacSHA256, access-key={COUPANG_ACCESS}, "
        f"signed-date={signed_date}, signature={signature}"
    )


def search_coupang(query: str) -> list[dict]:
    if not (COUPANG_ACCESS and COUPANG_SECRET):
        return []
    qs = urllib.parse.urlencode({"keyword": query, "limit": 10})
    data = http_get_json(
        f"{COUPANG_HOST}{COUPANG_PATH}?{qs}",
        {
            "Authorization": coupang_auth_header("GET", COUPANG_PATH, qs),
            "Content-Type": "application/json;charset=UTF-8",
        },
    )
    results = []
    for item in (data.get("data") or {}).get("productData", []) or []:
        try:
            price = int(item.get("productPrice") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        results.append({
            "source": "coupang",
            "title": clean_title(item.get("productName")),
            "price": price,
            "mall": "쿠팡",
            "link": item.get("productUrl"),
            "image": item.get("productImage"),
            "brand": "",
            "badge": "로켓배송" if item.get("isRocket") else "",
        })
    return results


# --------------------------------------------------------- 데모 데이터 ----
def search_demo(query: str) -> list[dict]:
    base = 50000 + (sum(map(ord, query)) % 50) * 10000
    malls = [
        ("네이버 가격비교", "naver", 1.00, "여러 판매처 비교"),
        ("쿠팡", "coupang", 0.97, "로켓배송"),
        ("11번가", "naver", 1.03, ""),
        ("G마켓", "naver", 0.99, ""),
        ("SSG.COM", "naver", 1.05, ""),
        ("옥션", "naver", 1.01, ""),
        ("롯데ON", "naver", 1.08, ""),
    ]
    items = [{
        "source": src,
        "title": f"{query} (데모 상품)",
        "price": int(round(base * ratio, -2)),
        "mall": mall,
        "link": "https://search.shopping.naver.com/search/all?query="
                + urllib.parse.quote(query),
        "image": "",
        "brand": "",
        "badge": badge,
    } for mall, src, ratio, badge in malls]
    # 액세서리처럼 보이는 저가 상품 (필터 동작 확인용)
    items.append({**items[0], "title": f"{query} 전용 케이스 (데모)",
                  "price": 9900, "mall": "스마트스토어", "badge": ""})
    return items


# --------------------------------------------------------- 필터·정렬 ----
ACCESSORY_WORDS = ["케이스", "커버", "필름", "보호필름", "거치대", "스트랩",
                   "파우치", "충전기", "케이블", "젠더", "스킨", "호환"]


def filter_results(query: str, items: list[dict], strict: bool) -> tuple[list[dict], int]:
    """strict=True 이면 액세서리·지나치게 싼 상품을 걸러냄"""
    if not strict or not items:
        return items, 0
    q = query.lower()
    words_in_query = [w for w in ACCESSORY_WORDS if w in q]
    kept = []
    for it in items:
        t = it["title"].lower()
        # 검색어에 없던 액세서리 단어가 제목에 있으면 제외
        if any(w in t and w not in words_in_query for w in ACCESSORY_WORDS):
            continue
        kept.append(it)
    # 중앙값의 35% 미만 가격은 다른 상품일 가능성이 높아 제외
    if len(kept) >= 4:
        median = statistics.median(i["price"] for i in kept)
        kept = [i for i in kept if i["price"] >= median * 0.35]
    return kept, len(items) - len(kept)


def dedupe(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in items:
        key = (it["mall"], it["title"], it["price"])
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def search_all(query: str, strict: bool) -> dict:
    cache_key = f"{query}|{strict}"
    hit = _cache.get(cache_key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]

    errors: dict[str, str] = {}
    items: list[dict] = []

    if DEMO_MODE:
        items = search_demo(query)
    else:
        sources = {"naver": search_naver, "coupang": search_coupang}
        with ThreadPoolExecutor(max_workers=len(sources)) as pool:
            futures = {name: pool.submit(fn, query) for name, fn in sources.items()}
            for name, fut in futures.items():
                try:
                    items.extend(fut.result())
                except Exception as e:  # 한 곳이 실패해도 나머지는 보여줌
                    errors[name] = str(e)

    items = dedupe(items)
    items, removed = filter_results(query, items, strict)
    items.sort(key=lambda i: i["price"])

    result = {
        "query": query,
        "demo": DEMO_MODE,
        "count": len(items),
        "filtered_out": removed,
        "cheapest": items[0] if items else None,
        "items": items[:60],
        "errors": errors,
        "sources": {
            "naver": bool(NAVER_ID and NAVER_SECRET),
            "coupang": bool(COUPANG_ACCESS and COUPANG_SECRET),
        },
    }
    if not errors:
        _cache[cache_key] = (time.time(), result)
    return result


# --------------------------------------------------------- HTTP 서버 ----
class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path in ("/", "/index.html"):
            body = (BASE_DIR / "index.html").read_bytes()
            return self._send(200, body, "text/html; charset=utf-8")
        if url.path == "/api/search":
            params = urllib.parse.parse_qs(url.query)
            query = (params.get("q") or [""])[0].strip()
            strict = (params.get("strict") or ["1"])[0] != "0"
            if not query:
                return self._send(400, b'{"error":"q is required"}', "application/json")
            result = search_all(query[:100], strict)
            body = json.dumps(result, ensure_ascii=False).encode("utf-8")
            return self._send(200, body, "application/json; charset=utf-8")
        self._send(404, b"Not Found", "text/plain")

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")


if __name__ == "__main__":
    print("=" * 50)
    print(" 최저가 비교 서버")
    print(f" 네이버 쇼핑 : {'연결됨' if NAVER_ID and NAVER_SECRET else '키 없음'}")
    print(f" 쿠팡 파트너스: {'연결됨' if COUPANG_ACCESS and COUPANG_SECRET else '키 없음'}")
    if DEMO_MODE:
        print(" ※ API 키가 없어 데모 데이터로 동작합니다 (.env 설정 필요)")
    print(f" 접속 주소   : http://localhost:{PORT}")
    print("=" * 50)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
