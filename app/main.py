"""웹 서버: 검색 페이지(/)와 JSON API(/api/search)."""
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .search import SORT_OPTIONS, normalize_sort, search

app = FastAPI(title="최저가 찾기")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["won"] = lambda n: f"{n:,}원"
templates.env.filters["safe_url"] = (
    lambda u: u if isinstance(u, str) and u.startswith(("http://", "https://")) else "#"
)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, q: str = "", sort: str = "price", strict: str | None = None):
    query = q.strip()
    sort = normalize_sort(sort)
    # 체크박스는 꺼져 있으면 값이 아예 오지 않는다.
    # 그래서 검색어가 있을 때만 strict 값을 보고, 첫 화면에서는 켜 둔다.
    strict_on = strict == "1" if query else True
    result = await search(query, strict_on, sort) if query else None
    sort_urls = {
        option: "/?" + urlencode({"q": query, "sort": option, "strict": "1" if strict_on else "0"})
        for option in SORT_OPTIONS
    }
    return templates.TemplateResponse(request, "index.html", {
        "query": query,
        "sort": sort,
        "strict": strict_on,
        "result": result,
        "sort_urls": sort_urls,
    })


@app.get("/api/search")
async def api_search(
    q: str = Query(..., max_length=100),
    sort: str = "price",
    strict: bool = True,
):
    if not q.strip():
        raise HTTPException(status_code=400, detail="q is required")
    return await search(q, strict, sort)
