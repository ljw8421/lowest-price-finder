# lowest-price-finder (최저가 찾기)

상품명을 입력하면 **네이버 쇼핑**(스마트스토어, 11번가, G마켓, SSG 등 네이버에 입점한 쇼핑몰)에서
가장 싼 곳부터 10개를 보여주고, 클릭하면 해당 상품 페이지로 이동합니다.
쿠팡 파트너스 API 키가 있으면 쿠팡도 함께 비교합니다.

개인용 도구라서 서버는 **이 PC에서만** 접속할 수 있게(`127.0.0.1`) 열립니다.

## 준비물

- Python 3.10 이상
- (선택) 네이버 검색 API 키: 없으면 데모 데이터로 화면만 확인할 수 있습니다.

## 설치 (처음 한 번)

**Mac / Linux**

```bash
cd lowest-price-finder
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

**Windows (PowerShell)**

```powershell
cd lowest-price-finder
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

> PowerShell에서 스크립트 실행이 막혀 있다면 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`를 한 번 실행하거나,
> 명령 프롬프트(cmd)에서 `.venv\Scripts\activate.bat`을 사용하세요.

## 실행

가상환경을 켠 상태에서 (Mac, Windows 공통):

```bash
python -m app
```

브라우저에서 http://127.0.0.1:8000 을 열면 됩니다. 포트는 `.env`의 `PORT`로 바꿀 수 있습니다.

## API 키 설정

`.env` 파일에 키를 채우세요. 둘 중 하나만 있어도 동작합니다. `.env`는 git에 올라가지 않습니다.

### 1. 네이버 쇼핑 (무료, 바로 발급)
1. https://developers.naver.com 에 로그인 → **Application > 애플리케이션 등록**
2. 사용 API에서 **검색** 선택, 환경은 **WEB**, 서비스 URL은 `http://127.0.0.1:8000`
3. 발급된 Client ID / Client Secret을 `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`에 입력

### 2. 쿠팡 파트너스 (선택, 승인 필요)
1. https://partners.coupang.com 가입
2. Open API 키는 **최종 승인된 파트너**만 발급받을 수 있습니다 (보통 일정 금액 이상의 판매 실적이 필요)
3. 발급된 Access Key / Secret Key를 `COUPANG_ACCESS_KEY`, `COUPANG_SECRET_KEY`에 입력

> 쿠팡 상품은 네이버 쇼핑 검색에 거의 나오지 않습니다. 쿠팡 키가 없으면 결과 위에
> "쿠팡에서 직접 확인하기" 검색 링크를 보여줍니다.

## 동작 방식

- 네이버에서 **정확도순 상위 100건**을 받아온 뒤, 그 안에서 **가격 낮은 순**으로 정렬해 10건을 보여줍니다.
  (처음부터 가격순으로 받으면 케이스·필름 같은 액세서리가 위를 채우기 때문입니다.)
  결과 위의 **가격순 / 관련도순**으로 정렬을 바꿀 수 있습니다.
- 중고, 단종, 판매예정 상품은 제외합니다.
- "액세서리 제외" 옵션(기본 켜짐)은 검색어에 없는 케이스·필름·충전기 같은 단어가 들어간 상품과
  중앙값의 35%보다 싼 상품(다른 상품일 가능성이 높음)을 걸러냅니다.
- 네이버와 쿠팡을 동시에 호출하고, 한쪽이 실패해도 다른 쪽 결과는 보여줍니다.
- 같은 검색어는 10분 동안 캐시해서 API 호출 한도를 아낍니다 (`CACHE_SECONDS`로 조절).
- 검색 결과 주소(`/?q=에어팟&sort=price&strict=1`)를 즐겨찾기해 두면 바로 다시 검색할 수 있습니다.
- JSON이 필요하면 `/api/search?q=에어팟&sort=price&strict=true`를 호출하세요.

## 알아둘 점

- 표시 가격은 **판매가**입니다. 배송비, 쿠폰, 카드 할인은 쇼핑몰 페이지에서 확인하세요.
- "네이버 가격비교"로 표시된 항목은 여러 판매처를 묶은 네이버 카탈로그 페이지로 연결되며, 그 안에서 판매처별 가격을 더 볼 수 있습니다.
- 네이버 검색 API는 하루 호출 횟수 제한(기본 25,000회)이 있습니다.

## 테스트

```bash
pytest
```

실제 API는 호출하지 않고 가짜 응답으로 필터링, 정렬, 화면을 확인합니다.

## 파일 구성

| 파일 | 역할 |
|---|---|
| `app/__main__.py` | 실행 진입점 (`python -m app`) |
| `app/main.py` | FastAPI 라우트: 검색 페이지 `/`, JSON API `/api/search` |
| `app/search.py` | 소스 동시 호출, 캐시, 필터링, 정렬 |
| `app/sources.py` | 네이버 / 쿠팡 API 호출과 응답 변환, 데모 데이터 |
| `app/config.py` | `.env` 설정 읽기 |
| `app/templates/index.html` | 검색 화면 (Jinja2) |
| `tests/` | pytest 테스트 |
