"""실행: python -m app  (Mac, Windows 공통)
키 확인: python -m app --check   (실제 API를 한 번 호출해 본다)
"""
import asyncio
import sys

import uvicorn

from .config import HOST, settings


def check_keys(query: str = "에어팟") -> int:
    """설정된 API 키로 실제 검색을 한 번 해 보고 결과를 출력한다."""
    from .search import fetch_all

    if settings.demo_mode:
        print("API 키가 없습니다. .env에 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET을 넣어 주세요.")
        return 1
    items, errors = asyncio.run(fetch_all(query))
    ok = True
    for name, enabled in (("naver", settings.naver_enabled), ("coupang", settings.coupang_enabled)):
        label = "네이버 쇼핑" if name == "naver" else "쿠팡 파트너스"
        if not enabled:
            print(f"- {label}: 키 없음 (건너뜀)")
        elif name in errors:
            ok = False
            print(f"- {label}: 실패 · {errors[name]}")
        else:
            count = sum(1 for it in items if it["source"] == name)
            print(f"- {label}: 정상 · '{query}' 검색 결과 {count}건")
    return 0 if ok else 1


def main() -> None:
    if "--check" in sys.argv[1:]:
        sys.exit(check_keys())

    print("=" * 50)
    print(" 최저가 찾기")
    print(f" 네이버 쇼핑  : {'키 있음' if settings.naver_enabled else '키 없음'}")
    print(f" 쿠팡 파트너스: {'키 있음' if settings.coupang_enabled else '키 없음'}")
    if settings.demo_mode:
        print(" ※ API 키가 없어 데모 데이터로 동작합니다 (.env 설정 필요)")
    else:
        print(" 키가 맞는지 확인하려면: python -m app --check")
    print(f" 접속 주소    : http://{HOST}:{settings.port}")
    print("=" * 50)
    uvicorn.run("app.main:app", host=HOST, port=settings.port)


if __name__ == "__main__":
    main()
