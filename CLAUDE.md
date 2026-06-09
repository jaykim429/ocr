# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.
- Distinguish observed from assumed. Verify before claiming success - prefer reproducible evidence (a test, a run, direct inspection) over confident phrasing. If you can't verify something, say so.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

## 5. 프로젝트 특화 규칙 — AI 사전 QA 자동화(식품)

현대홈쇼핑 식품 입점서류를 4단계(1.인허가 · 2.영양성분 · 3.자가품질 · 4.표시사항)로 검토한다. 아래는 이전 작업에서 **실제 코드·결과로 검증된** 결정이다. 추측이 아니라 확인된 것만 둔다. 도메인 용어 정확성을 위해 이 절은 한국어로 둔다.

### 아키텍처 (바꾸기 전 반드시 확인)

- 최종 판정(적합/검토필요/부적합)은 **Gemma VLM이 수행**한다. 파이썬(`pipeline`·`*_check`)은 근거(evidence) 구성·식품공전/인허가 API 조회·OCR만 담당한다. 판정을 파이썬 규칙엔진으로 대체하지 말 것.
- 고유명사(제품명·제조사·주소)·날짜는 **로컬 PaddleOCR(`ocr_engines.py`)이 권위**다. Gemma 비전은 스캔 작은 글씨를 환각/오독한다(실측: '한둘 도토리묵가루'→'한돌 토마토가루', 발급일 누락, 가짜 주소 생성 1/8). → 추출값이 OCR 원문과 다르면 OCR을 신뢰. `cross_check_documents`·`license_check`·`label_check`에 `_ocr_text` 권위 가드가 적용돼 있으니 새 비교 로직도 동일 패턴을 따를 것.
- 원격 Gemma 엔드포인트는 `settings`(REVIEW_*). **폐쇄망** 전제 — 외부 주소 변환 API(juso/Kakao)는 작동하지 않으니 도입 금지.
- 비밀키는 `API_KEYS.md`(gitignored)에만 둔다. CLAUDE.md·소스에 키를 inline 하지 말 것.

### 도메인 판정 규칙 (검증됨 — 임의로 바꾸지 말 것)

- **유효기간 = 발급일 + 6개월 고정**(현대홈쇼핑 기준). 식품유형별 법정 검사주기는 참고용일 뿐 유효기간 판정에 쓰지 않는다.
- **규격 적용조건 단서 절대우선**: 멸균제품만 세균수, 살균제품만 대장균군, "그대로 섭취하는 제품에 한함"이면 조리·가열 제품(표시사항에 조리법 있음)은 대장균 면제. 미사용 첨가물 검사항목은 누락이 아니다.
- **과다알람 방지가 최우선**: 불확실하면 '부적합' 단정 말고 '검토필요'. 규격을 못 읽으면 안전하다고 단정하지 말 것.
- **주소 불일치**: 전치(수내↔내수, 글자집합 동일)=실제 오기→플래그. 치환·1글자(철곡↔칠곡, 삼향↔심향)=OCR 오인식→보류. 번지 숫자차=실제→플래그. 도로명주소 읍·면 지역은 읍·면 표기가 원칙. 1·4단계는 동일 공식주소(`_official_address`)를 쓴다.
- **식품유형**: 접두 누락(기타수산물가공품 ⊃ 수산물가공품)은 같은 계열(불일치 아님).
- **오버피팅 금지**: 한 샘플에 맞춘 규칙을 넣지 말 것. 변경 후 다른 케이스로 보편성을 검증한다(예: 짧은 일반명 거짓일치 방지용 변별력 길이 가드).

### 검증 방법 (성공 주장 전 필수)

- 실제 업로드 서류는 `data/reviews/{job_id}/input/`, 추출/판정 결과는 `data/reviews/{job}/out/.../review_report.json`. 의심되면 `render_file` + `ocr_image_best`로 직접 렌더·OCR해 눈으로 대조한 뒤 결론낸다.
- 테스트: `python -m pytest -q` — `tests/test_qa_features.py`는 순수 로직(네트워크/Gemma 불필요). 새 판정 규칙엔 회귀 테스트를 추가한다.
- 콘솔이 cp949라 한글이 깨진다 → 진단 스크립트는 `PYTHONIOENCODING=utf-8`로 실행하고, 임시 실험 스크립트는 `_` 접두(미추적)로 둔다.
- 추출은 `chandra/data/extraction_cache`에 캐시(파일해시+프롬프트버전 키). 프롬프트를 바꾸면 캐시가 자동 무효화된다.

### 법령·배포

- 감시법령: `chandra/data/law_watchlist.json` → `law_monitor.check_updates()`로 `law_monitor.json` DB 적재 → `/laws` 탭(법제처 OpenAPI). 단일 고시 본문은 `law_attachment`에서 글씨크기(heading) 정규화됨. 표시사항 분석에 연결되는 고시는 `law_rules.py`(트리거 기반 프롬프트 그라운딩).
- 배포: **fork(`jaykim429/ocr`)** 에 push한다. `origin`은 upstream(`datalab-to/chandra`)이므로 push하지 말 것.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
