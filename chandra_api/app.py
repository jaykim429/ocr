"""품질검토 REST API (FastAPI).

엔드포인트:
  POST /auth/login            (username, password) → JWT
  POST /reviews               서류 업로드(zip 또는 다중 파일) → job_id (비동기 실행)
  GET  /reviews               내 검토 잡 목록
  GET  /reviews/{id}          잡 상태 + 결과 리포트
  GET  /agencies              검사기관 DB 요약
  GET  /health
인증: Authorization: Bearer <token>
"""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from chandra_api import auth, jobs

app = FastAPI(title="식품 품질검토 API", version="0.1.0")

# 프런트(개발 Vite :5173 등) 허용. 운영 도메인은 QR_CORS_ORIGINS(쉼표구분)로 지정.
_origins = os.environ.get("QR_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

_bearer = HTTPBearer(auto_error=True)


def current_user(cred: HTTPAuthorizationCredentials = Depends(_bearer)) -> str:
    user = auth.decode_token(cred.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰")
    return user


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/auth/login")
def login(username: str = Form(...), password: str = Form(...)) -> dict:
    if not auth.authenticate(username, password):
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다")
    return {"access_token": auth.create_token(username), "token_type": "bearer"}


@app.get("/agencies")
def agencies(user: str = Depends(current_user)) -> dict:
    from collections import Counter

    from chandra.test_agencies import load_agency_db

    db = load_agency_db()
    return {"count": len(db), "by_category": dict(Counter(a.category for a in db))}


@app.get("/agencies/list")
def agencies_list(
    q: str | None = None, category: str | None = None, user: str = Depends(current_user)
) -> dict:
    """검사기관 DB 조회(검색/분야 필터)."""
    from chandra.test_agencies import load_agency_db
    from chandra.text_match import collapse

    db = load_agency_db()
    items = [a.to_dict() for a in db]
    if category:
        items = [a for a in items if a.get("category") == category]
    if q:
        nq = collapse(q)
        items = [
            a for a in items
            if nq in collapse(a.get("name")) or nq in collapse(a.get("designation_no"))
            or nq in (a.get("tel") or "") or nq in collapse(a.get("address"))
        ]
    return {"count": len(items), "items": items}


@app.get("/business/search")
def business_search(
    q: str | None = None,
    license_no: str | None = None,
    industry: str | None = None,
    address: str | None = None,
    user: str = Depends(current_user),
) -> dict:
    """식약처 식품안전나라 인허가 업소 검색(I2500).

    상세 필터(업소명 q·영업등록번호·업종·소재지)를 서버 조건으로 조합 검색한다.
    q 가 숫자만이면 영업등록번호로 간주한다(편의).
    """
    from chandra.foodsafety import search_license

    q = (q or "").strip()
    name = q or None
    lic = (license_no or "").strip() or None
    # q 가 숫자 8자리 이상이면 영업등록번호로 처리
    if name and not lic:
        digits = "".join(c for c in name if c.isdigit())
        if digits and len(digits) >= 8 and digits == name.replace("-", "").replace(" ", ""):
            name, lic = None, digits
    if not any([name, lic, industry, address]):
        return {"count": 0, "items": []}
    try:
        records = search_license(
            business_name=name, license_no=lic,
            industry=(industry or "").strip() or None,
            address=(address or "").strip() or None,
        )
        return {"count": len(records), "items": [r.to_dict() for r in records]}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"업체 검색 실패: {e}")


@app.get("/laws")
def laws(user: str = Depends(current_user)) -> dict:
    """식약처 식품 관련 법령·행정규칙 감시목록 + (수집되어 있으면) 현행/시행예정 상태."""
    import json as _json

    from chandra.law_monitor import _DB_PATH, load_watchlist

    monitored: dict = {}
    if _DB_PATH.exists():
        monitored = _json.loads(_DB_PATH.read_text(encoding="utf-8")).get("items", {})
    out = []
    for w in load_watchlist():
        key = f"{w['kind']}:{w['name']}"
        rec = monitored.get(key) or {}
        cur = rec.get("current") or {}
        out.append({
            "name": w["name"], "kind": w["kind"],
            "status": cur.get("status", "미수집"),
            "enforce_date": cur.get("enforce_date"),
            "promulgation_date": cur.get("promulgation_date"),
            "revision_type": cur.get("revision_type"),
            "upcoming_enforce_date": cur.get("upcoming_enforce_date"),
            "upcoming_seq": cur.get("upcoming_seq"),
            "seq": cur.get("seq"),
            "history": rec.get("history", []),
        })
    return {"items": out, "note": ""}


@app.get("/laws/body")
def law_body(seq: str, target: str = "eflaw", user: str = Depends(current_user)) -> dict:
    """법령/행정규칙 본문을 본문(조문)·부칙·별표(첨부링크)로 구조화해 반환."""
    from chandra import law

    try:
        return law.get_law_body(seq, target=target)
    except law.LawAuthError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"법령 본문 조회 실패: {e}")


@app.get("/laws/attachment")
def law_attachment(link: str, user: str = Depends(current_user)) -> dict:
    """고시전문 첨부파일(HWPX/HWP/ZIP)을 마크다운으로 변환(캐시). 식품공전·표시기준 본문 렌더용."""
    from chandra import law_attachment as la

    try:
        return la.attachment_markdown(link)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"첨부파일 변환 실패: {e}")


_SUPPORTED = {".zip", ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tiff", ".bmp", ".gif",
              ".hwp", ".hwpx", ".docx", ".xlsx", ".xls"}


@app.post("/reviews")
async def create_review(
    files: list[UploadFile] = File(...),
    today: str | None = Form(None),
    user: str = Depends(current_user),
) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="업로드된 파일이 없습니다")
    job_id = jobs.create_job(input_name=", ".join(f.filename for f in files), owner=user)
    src = jobs.work_dir(job_id) / "input"
    src.mkdir(parents=True, exist_ok=True)
    for f in files:
        if Path(f.filename).suffix.lower() not in _SUPPORTED:
            continue
        (src / Path(f.filename).name).write_bytes(await f.read())
    saved = list(src.iterdir())
    zips = [f for f in saved if f.suffix.lower() == ".zip"]
    # zip 여러 개 = 검토대상 여러 개(병렬 판정), zip 한 개 = 그 zip, 그 외 = 폴더 전체를 한 단위로
    if len(zips) >= 2:
        inputs = zips
    elif len(zips) == 1 and len(saved) == 1:
        inputs = [zips[0]]
    else:
        inputs = [src]
    today_d = datetime.strptime(today, "%Y-%m-%d").date() if today else date.today()
    jobs.start_job(job_id, inputs, jobs.work_dir(job_id) / "out", today=today_d)
    return {"job_id": job_id, "status": "pending"}


@app.get("/foodcode/spec")
def foodcode_spec(product_type: str, user: str = Depends(current_user)) -> dict:
    """식품공전(I0930) 식품유형별 시험항목·기준규격 조회 — 자가품질 결과 대조·인용용."""
    from chandra.foodsafety import search_food_spec

    try:
        rows = search_food_spec((product_type or "").strip())
        return {"product_type": product_type, "count": len(rows), "items": rows}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"식품공전 조회 실패: {e}")


@app.get("/reviews")
def my_reviews(user: str = Depends(current_user)) -> dict:
    return {"jobs": jobs.list_jobs(owner=user)}


@app.get("/reviews/{job_id}")
def get_review(job_id: str, user: str = Depends(current_user)) -> dict:
    job = jobs.get_job(job_id)
    if not job or job.get("owner") != user:
        raise HTTPException(status_code=404, detail="잡을 찾을 수 없습니다")
    return job
