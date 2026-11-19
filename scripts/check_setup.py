"""작업 환경 점검 스크립트 (표준 라이브러리만 사용, Mac/Windows 공통).

직접 실행:   python3 scripts/check_setup.py
Claude Code: 세션 시작 시 .claude/settings.json 의 SessionStart 훅이 --hook 으로 실행한다.
            --hook 이면 JSON을 출력해서, 요약은 사용자 화면에, 전체 내용은 Claude 컨텍스트에 넣는다.

API 키 값은 절대 출력하지 않는다 (있음/없음만 표시).
"""
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY_VALID_DAYS = 180  # 11번가 OpenAPI 인증키 유효기간 (2026-06-30 시행)
KEY_WARN_DAYS = 30


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def venv_python() -> Path | None:
    for rel in (".venv/bin/python", ".venv/Scripts/python.exe"):
        p = ROOT / rel
        if p.exists():
            return p
    return None


def run(cmd: list[str]) -> tuple[int, str]:
    try:
        out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=20)
        return out.returncode, (out.stdout + out.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def check() -> tuple[list[tuple[str, str, str]], list[str]]:
    """(상태, 항목, 내용) 목록과 다음에 할 일 목록을 돌려준다. 상태: ok / warn / fail"""
    rows: list[tuple[str, str, str]] = []
    todo: list[str] = []

    # git
    code, branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    _, dirty = run(["git", "status", "--porcelain"])
    if code == 0:
        changed = len([l for l in dirty.splitlines() if l.strip()])
        rows.append(("ok" if not changed else "warn", "git",
                     f"브랜치 {branch}" + (f", 커밋 안 된 변경 {changed}개" if changed else ", 변경 없음")))
    else:
        rows.append(("warn", "git", "git 저장소가 아님"))

    # 가상환경과 패키지
    py = venv_python()
    if not py:
        rows.append(("fail", "venv", ".venv 없음"))
        todo.append("가상환경 만들기: README의 '설치' 참고 (python -m venv .venv → pip install -r requirements.txt)")
    else:
        code, out = run([str(py), "-c",
                         "import sys,fastapi,uvicorn,jinja2,httpx,dotenv,pytest;"
                         "print('%d.%d.%d' % sys.version_info[:3])"])
        if code == 0:
            ver = out.splitlines()[-1]
            major, minor = (int(x) for x in ver.split(".")[:2])
            rows.append(("ok" if (major, minor) >= (3, 10) else "fail", "venv",
                         f"Python {ver}, 패키지 설치됨"))
        else:
            rows.append(("fail", "venv", "패키지 누락: pip install -r requirements.txt 필요"))
            todo.append("패키지 설치: .venv의 pip로 pip install -r requirements.txt")

    # .env와 API 키 (값은 출력하지 않음)
    env = read_env(ROOT / ".env")
    if not (ROOT / ".env").exists():
        rows.append(("fail", ".env", "없음 (.env.example을 복사해서 만들기)"))
        todo.append(".env 만들기: .env.example 복사")
    else:
        has_11st = bool(env.get("ELEVENST_API_KEY"))
        has_coupang = bool(env.get("COUPANG_ACCESS_KEY") and env.get("COUPANG_SECRET_KEY"))
        rows.append(("ok" if has_11st else "warn", "11번가 키",
                     "있음" if has_11st else "없음 → 데모 모드로 동작"))
        rows.append(("ok", "쿠팡 키", "있음" if has_coupang else "없음 (파트너스 최종 승인 전, 정상)"))
        if not has_11st:
            todo.append("11번가 Open API 키 발급 후 .env의 ELEVENST_API_KEY에 입력 (CLAUDE.md '다음 할 일' 참고)")
        issued = env.get("ELEVENST_KEY_ISSUED", "")
        if has_11st and issued:
            try:
                left = (dt.date.fromisoformat(issued) + dt.timedelta(days=KEY_VALID_DAYS) - dt.date.today()).days
                status = "ok" if left > KEY_WARN_DAYS else ("warn" if left > 0 else "fail")
                rows.append((status, "11번가 키 만료", f"{left}일 남음 (발급·갱신일 {issued} 기준)"))
                if left <= KEY_WARN_DAYS:
                    todo.append("11번가 키 갱신: OPEN API 센터 > API 관리 (만료 60일 전부터 가능), 갱신 후 ELEVENST_KEY_ISSUED 수정")
            except ValueError:
                rows.append(("warn", "11번가 키 만료", f"ELEVENST_KEY_ISSUED 형식 오류: {issued} (YYYY-MM-DD)"))
        elif has_11st:
            rows.append(("warn", "11번가 키 만료", "ELEVENST_KEY_ISSUED 미입력 → 만료일 계산 불가"))

    # 브라우저 자동화용 MCP (키 발급 같은 사이트 작업에 사용, 선택)
    found = False
    for cfg in (Path.home() / ".claude.json", Path.home() / ".claude" / ".claude.json"):
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            found = found or "chrome-devtools" in (data.get("mcpServers") or {})
        except (OSError, ValueError):
            pass
    rows.append(("ok" if found else "warn", "chrome-devtools MCP",
                 "설정됨" if found else "없음 (사이트 작업이 필요할 때만 추가)"))

    return rows, todo


def main() -> None:
    rows, todo = check()
    icon = {"ok": "✅", "warn": "⚠️", "fail": "❌"}
    lines = [f"{icon[s]} {name}: {msg}" for s, name, msg in rows]
    if todo:
        lines.append("다음에 할 일:")
        lines += [f"  - {t}" for t in todo]
    report = "\n".join(lines)

    if "--hook" not in sys.argv[1:]:
        print("[lowest-price-finder 환경 점검]")
        print(report)
        return

    fails = sum(1 for s, *_ in rows if s == "fail")
    warns = sum(1 for s, *_ in rows if s == "warn")
    summary = ("환경 점검: 이상 없음" if not (fails or warns)
               else f"환경 점검: 실패 {fails}개, 확인 필요 {warns}개 (자세한 내용은 Claude에게 물어보세요)")
    context = ("[lowest-price-finder 세션 시작 환경 점검 결과]\n" + report +
               "\n\n작업을 시작하기 전에 CLAUDE.md의 '현재 상태'와 '다음 할 일'을 확인하고, "
               "실패(❌)나 확인 필요(⚠️) 항목이 이번 작업에 영향을 주면 먼저 사용자에게 알려라.")
    print(json.dumps({
        "systemMessage": summary,
        "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context},
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
