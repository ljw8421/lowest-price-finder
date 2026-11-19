import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import search as search_module  # noqa: E402
from app.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """실제 .env 키와 무관하게 데모 모드, 빈 캐시로 테스트한다."""
    for key in ("naver_client_id", "naver_client_secret",
                "coupang_access_key", "coupang_secret_key"):
        monkeypatch.setattr(settings, key, "")
    search_module.clear_cache()
    yield
    search_module.clear_cache()


def make_item(price, title="상품", mall="몰", source="naver", rank=0):
    return {"source": source, "title": title, "price": price, "mall": mall,
            "link": "https://example.com", "image": "", "brand": "", "badge": "",
            "rank": rank}
