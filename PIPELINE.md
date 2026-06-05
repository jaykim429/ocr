# 품질검토 자동화 파이프라인

현대홈쇼핑 입점 식품 고객사가 제출하는 인허가/품질 서류의 적합성을 OCR + 식약처 API +
식품공전 규격 + Gemma 판정으로 자동 검토한다.

## 핵심 설계

- **판독(OCR)**: 로컬에 GPU/vLLM이 없어 chandra 모델 대신 **Gemma4 비전 모델**
  (`google/gemma-4-26B-A4B-it`, `REVIEW_API_BASE`)로 문서를 직접 판독·분류·필드추출한다.
  PDF/이미지는 `pypdfium2`로 고해상도(긴 변 2400px) 렌더 후 전달한다.
- **판단(적합성 판정)**: 규칙엔진이 아니라 **Gemma가 수행**한다. 파이썬은 API 조회·
  식품공전 규격 조회·교차대조·유효기간·검사기관 검증 등 **근거(evidence)만 구조화**해
  Gemma에 전달하고, Gemma가 낸 JSON 판정을 사용한다.

## 단계

| 단계 | 모듈 | 내용 |
|---|---|---|
| 1. 인허가 적합성 | `license_check.py`, `foodsafety.py` | 식품안전나라 인허가 DB(I2500)에 영업자 존재 확인 + 인허가서류 영업자명·주소가 표시사항과 일치하는지 대조 |
| 2. 영양성분 비교 | `nutrition.py` | 표시사항 ↔ 영양성분성적서 실측 비교. 「식품등의 표시기준」 허용오차(상한 120% / 하한 80%) 계산 |
| 3. 자가품질검사 | `self_quality.py`, `food_code.py`, `test_agencies.py`, `validity.py` | 품목제조보고서↔성적서 교차대조, 식품공전 규격 범위 내 결과인지, 항목 충분성(누락), 검사기관 공인 여부, 발급일 기준 6개월 유효기간 |

### 판정 기준 메모
- 3단계 적합 = **성적서 시험결과값이 식품공전 규격 범위 안에 들면 적합**
  (성적서 인쇄기준 표기가 식품공전과 달라도 결과가 범위에 들면 적합).
- 서류 유효기간 = **발급일 + 6개월**, 항상 오늘 날짜 기준.
- 검사기관 = 공인 위생검사전문기관 목록(`chandra/data/test_agencies.json`)에 존재해야 함.

## 사용법

### 로컬 UI (Streamlit)
```bash
pip install -e ".[app]"      # streamlit 설치
quality-review-app           # 브라우저에서 http://localhost:8501
```
서류(zip 또는 PDF/이미지 다중)를 업로드 → '검토 실행' → 단계별 판정·근거·다운로드.

### CLI
```bash
# 위생검사전문기관 목록을 DB로 인제스트 (자가품질검사 매뉴얼 2018: 0-기준 82~91쪽 = 식품+축산물)
quality-review --ingest-agencies "식품등의+자가품질검사+매뉴얼(2018.1).pdf" --agency-pages 82-91

# zip(또는 폴더/단일파일) 입력 → 자동 검토 리포트 생성
quality-review samples/현대홈쇼핑_입점서류.zip out/review
quality-review samples/ out/review --today 2026-06-02
```

출력: `out/review/review_report.json` (전체 근거+판정), `review_report.md` (요약).

> 참고: 검사기관 목록은 PDF **텍스트 레이어**를 추출해 Gemma로 구조화한다(스캔 이미지 OCR 대비 정확). Gemma 호출이 느려(페이지당 ~100초) 여러 페이지를 묶어 호출한다.

## 설정 (`chandra/settings.py`)
- `FOODSAFETY_API_KEY` / `FOODSAFETY_LICENSE_SERVICE`(I2500): 인허가 조회. 현재 키는 I2500만 인가.
- `REVIEW_API_BASE` / `REVIEW_MODEL_NAME`: Gemma 판독·판정 엔드포인트.

## 향후
- 4단계(건기식 광고심의필증 ↔ 웹기술서 비교)는 신규 워크플로로 추가 예정.
- 식품공전 규격 수치는 `food_code.py`의 정적 룰셋. 식품공전 API 인가 시 동적 로딩으로 대체.
