from dotenv import find_dotenv
from pydantic_settings import BaseSettings
import os


class Settings(BaseSettings):
    # Paths
    BASE_DIR: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # 문서 렌더링/레이아웃 파싱 공통 설정 (input.py/output.py 에서 사용)
    IMAGE_DPI: int = 192
    MIN_PDF_IMAGE_DIM: int = 1024
    MIN_IMAGE_DIM: int = 1536
    MAX_OUTPUT_TOKENS: int = 12384
    BBOX_SCALE: int = 1000

    # 식품안전나라(식약처) 오픈API
    # 키는 서비스별로 인가된다. 현재 키는 I2500(인허가 업소 정보)에만 인가됨.
    FOODSAFETY_API_KEY: str = "063016cf022a49c3816e"
    FOODSAFETY_API_BASE: str = "http://openapi.foodsafetykorea.go.kr/api"
    FOODSAFETY_LICENSE_SERVICE: str = "I2500"  # 인허가 업소 정보
    FOODSAFETY_PRDLST_SERVICE: str = "I1250"  # 품목제조보고 정보 (식품유형 조회용, 인가 필요)
    FOODSAFETY_TIMEOUT_SECONDS: float = 20.0

    # 도로명주소 OpenAPI(juso.go.kr) 키 (선택; 주소 도로명↔지번 정규화 검증용)
    JUSO_API_KEY: str = ""

    # 법제처 국가법령정보 OPEN API (행정규칙/별표 = 식품공전·표시기준·검사항목)
    # OC = 사용자 ID. 호출 서버 IP/도메인을 open.law.go.kr 에 사전 등록해야 동작한다.
    LAW_OC: str = "wjdgns429"
    LAW_API_BASE: str = "https://www.law.go.kr"
    LAW_TIMEOUT_SECONDS: float = 20.0

    # OCR review/refinement settings
    REVIEW_API_KEY: str = "EMPTY"
    REVIEW_API_BASE: str = "http://222.110.207.7:8000/v1"
    REVIEW_MODEL_NAME: str = "google/gemma-4-26B-A4B-it"
    REVIEW_MAX_OUTPUT_TOKENS: int = 8192
    REVIEW_TIMEOUT_SECONDS: float = 120.0
    REVIEW_MAX_CONCURRENCY: int = 12  # 원격 VLM 동시 호출 상한(중첩 스레드풀 과부하 방지)
    REVIEW_INCLUDE_IMAGE: bool = True
    REVIEW_MAX_INPUT_CHARS: int = 60000

    class Config:
        env_file = find_dotenv("local.env")
        extra = "ignore"


settings = Settings()
