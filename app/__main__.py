"""실행: python -m app  (Mac, Windows 공통)"""
import uvicorn

from .config import HOST, settings


def main() -> None:
    print("=" * 50)
    print(" 최저가 찾기")
    print(f" 네이버 쇼핑  : {'연결됨' if settings.naver_enabled else '키 없음'}")
    print(f" 쿠팡 파트너스: {'연결됨' if settings.coupang_enabled else '키 없음'}")
    if settings.demo_mode:
        print(" ※ API 키가 없어 데모 데이터로 동작합니다 (.env 설정 필요)")
    print(f" 접속 주소    : http://{HOST}:{settings.port}")
    print("=" * 50)
    uvicorn.run("app.main:app", host=HOST, port=settings.port)


if __name__ == "__main__":
    main()
