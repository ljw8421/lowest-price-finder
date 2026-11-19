"""설정: 프로젝트 폴더의 .env 파일과 환경 변수에서 읽는다."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# 개인용 도구이므로 이 PC에서만 접속할 수 있게 연다.
HOST = "127.0.0.1"


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    return int(value) if value else default


@dataclass
class Settings:
    elevenst_api_key: str = ""
    coupang_access_key: str = ""
    coupang_secret_key: str = ""
    port: int = 8000

    @property
    def elevenst_enabled(self) -> bool:
        return bool(self.elevenst_api_key)

    @property
    def coupang_enabled(self) -> bool:
        return bool(self.coupang_access_key and self.coupang_secret_key)

    @property
    def demo_mode(self) -> bool:
        """API 키가 하나도 없으면 가짜 데이터로 화면만 보여준다."""
        return not (self.elevenst_enabled or self.coupang_enabled)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            elevenst_api_key=os.getenv("ELEVENST_API_KEY", "").strip(),
            coupang_access_key=os.getenv("COUPANG_ACCESS_KEY", "").strip(),
            coupang_secret_key=os.getenv("COUPANG_SECRET_KEY", "").strip(),
            port=_int_env("PORT", 8000),
        )


settings = Settings.from_env()
