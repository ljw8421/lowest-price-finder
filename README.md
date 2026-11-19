# lowest-price-finder (최저가 찾기)

상품명을 입력하면 **11번가**에서 가장 싼 상품부터 10개를 보여주고, 클릭하면 해당 상품 페이지로 이동합니다.
쿠팡 파트너스 API 키가 있으면 쿠팡도 함께 비교합니다.
네이버 쇼핑과 쿠팡(키가 없을 때)은 같은 검색어로 바로 가는 링크를 보여줍니다.

개인용 도구라서 서버는 **이 PC에서만** 접속할 수 있게(`127.0.0.1`) 열립니다.

> 네이버 쇼핑 검색 API는 2026년 7월 31일에 종료되어 더 이상 쓸 수 없습니다.

## 준비물

- Python 3.10 이상
- (선택) 11번가 Open API 키: 없으면 데모 데이터로 화면만 확인할 수 있습니다.

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

환경이 제대로 갖춰졌는지는 `python3 scripts/check_setup.py`로 확인할 수 있습니다.

## 실행

가상환경을 켠 상태에서 (Mac, Windows 공통):

```bash
python -m app
```

브라우저에서 http://127.0.0.1:8000 을 열면 됩니다. 포트는 `.env`의 `PORT`로 바꿀 수 있습니다.

## API 키 설정

`.env` 파일에 키를 채우세요. `.env`는 git에 올라가지 않습니다.

### 1. 11번가 Open API (무료, 판매자 회원만 발급)
1. https://openapi.11st.co.kr 에서 **API 관리**로 들어가 로그인한 뒤 키를 발급받습니다. **11번가 판매자(셀러) 회원만** 발급받을 수 있습니다. 일반 회원으로 들어가면 판매자 가입 안내가 나옵니다.
2. 발급된 32자리 키를 `ELEVENST_API_KEY`에, 발급한 날짜를 `ELEVENST_KEY_ISSUED`(예: `2026-11-19`)에 입력합니다.
3. 키가 맞는지 확인:

   ```bash
   python -m app --check
   ```

   `11번가: 정상 · '에어팟' 검색 결과 N건`이 나오면 됩니다.

알아둘 점:
- 키는 **발급·갱신일로부터 180일** 동안 유효합니다. 계속 쓰면 자동으로 연장되고, 180일 동안 쓰지 않으면 끊깁니다.
- 회원 1명당 키는 1개만 받을 수 있고, 다른 사람과 공유하면 안 됩니다.
- 약관상 받은 데이터를 저장할 수 없어서, 이 도구는 검색 결과를 캐시하지 않고 매번 새로 조회합니다.

### 2. 쿠팡 파트너스 (선택, 승인 필요)
1. https://partners.coupang.com 가입 후 활동 채널(블로그 등)을 등록합니다.
2. 파트너스 링크로 **누적 판매 15만 원 이상**이 되면 채널 검토 후 **최종 승인**이 나고, 그때부터 파트너스 API를 쓸 수 있습니다.
3. 발급된 Access Key / Secret Key를 `COUPANG_ACCESS_KEY`, `COUPANG_SECRET_KEY`에 입력합니다.

## 동작 방식

- 11번가에서 **인기도순 상위 100건**을 받아온 뒤, 그 안에서 **가격 낮은 순**으로 정렬해 10건을 보여줍니다.
  (처음부터 가격순으로 받으면 케이스·필름 같은 액세서리가 위를 채우기 때문입니다.)
  결과 위의 **가격순 / 관련도순**으로 정렬을 바꿀 수 있습니다.
- "액세서리 제외" 옵션(기본 켜짐)은 검색어에 없는 케이스·필름·충전기 같은 단어가 들어간 상품과
  중앙값의 35%보다 싼 상품(다른 상품일 가능성이 높음)을 걸러냅니다.
- 11번가와 쿠팡을 동시에 호출하고, 한쪽이 실패해도 다른 쪽 결과는 보여줍니다.
- 검색 결과 주소(`/?q=에어팟&sort=price&strict=1`)를 즐겨찾기해 두면 바로 다시 검색할 수 있습니다.
- JSON이 필요하면 `/api/search?q=에어팟&sort=price&strict=true`를 호출하세요.

## 알아둘 점

- 11번가 가격은 **할인모음가**(없으면 판매가) 기준입니다. 쿠폰과 카드 할인은 상품 페이지에서 확인하세요.
- 같은 상품이라도 판매자마다 따로 나옵니다. 목록에 판매자 이름이 함께 표시됩니다.

## 테스트

```bash
pytest
```

실제 API는 호출하지 않고 가짜 응답으로 응답 변환, 필터링, 정렬, 화면을 확인합니다.

## 파일 구성

| 파일 | 역할 |
|---|---|
| `app/__main__.py` | 실행 진입점 (`python -m app`, `python -m app --check`) |
| `app/main.py` | FastAPI 라우트: 검색 페이지 `/`, JSON API `/api/search` |
| `app/search.py` | 소스 동시 호출, 필터링, 정렬 |
| `app/sources.py` | 11번가 / 쿠팡 API 호출과 응답 변환, 바로가기 링크, 데모 데이터 |
| `app/config.py` | `.env` 설정 읽기 |
| `app/templates/index.html` | 검색 화면 (Jinja2) |
| `scripts/check_setup.py` | 환경 점검 (Claude Code 세션 시작 시 자동 실행) |
| `CLAUDE.md` | 결정 사항, 현재 상태, 다음 할 일 (Claude Code 작업 기록) |
| `tests/` | pytest 테스트 |
