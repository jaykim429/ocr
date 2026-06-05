"""품질검토 파이프라인 로컬 UI (Streamlit).

실행: quality-review-app  (또는 streamlit run chandra/scripts/review_app.py)
"""

from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path

import streamlit as st

from chandra.pipeline import run_quality_review
from chandra.settings import settings
from chandra.test_agencies import load_agency_db


_VERDICT_COLOR = {
    "적합": "🟢",
    "부적합": "🔴",
    "검토필요": "🟡",
    "판정불가": "⚪",
}


def _verdict_badge(verdict: str | None) -> str:
    if not verdict:
        return "⚪ -"
    icon = _VERDICT_COLOR.get(verdict, "⚪")
    return f"{icon} **{verdict}**"


def _save_uploads(files, work: Path) -> Path:
    src = work / "input"
    src.mkdir(parents=True, exist_ok=True)
    for uf in files:
        (src / uf.name).write_bytes(uf.getbuffer())
    # zip 하나만 올라온 경우 그 zip 경로를 직접 반환
    paths = list(src.iterdir())
    if len(paths) == 1 and paths[0].suffix.lower() == ".zip":
        return paths[0]
    return src


def main():
    st.set_page_config(page_title="식품 입점서류 품질검토", page_icon="🧪", layout="wide")
    st.title("🧪 식품 입점서류 품질검토 자동화")
    st.caption(
        "표시사항·품목제조보고서·자가품질검사성적서·영양성분성적서를 업로드하면 "
        "OCR·식약처 인허가 조회·식품공전 규격·검사기관/유효기간을 근거로 Gemma가 적합성을 판정합니다."
    )

    with st.sidebar:
        st.header("설정")
        today_str = st.date_input("유효기간 기준일(오늘)", value=date.today())
        max_pages = st.number_input("문서당 판독 페이지 수", 1, 20, 4)
        st.divider()
        st.subheader("엔드포인트")
        st.text(f"판독·판정(Gemma): {settings.REVIEW_MODEL_NAME}")
        st.text(f"인허가 API: {settings.FOODSAFETY_LICENSE_SERVICE}")
        db = load_agency_db()
        st.text(f"공인 검사기관 DB: {len(db)}개")

    files = st.file_uploader(
        "서류 업로드 (zip 또는 PDF/이미지 다중 선택)",
        type=["zip", "pdf", "png", "jpg", "jpeg", "webp", "tiff", "bmp"],
        accept_multiple_files=True,
    )

    if st.button("검토 실행", type="primary", disabled=not files):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            input_path = _save_uploads(files, work)
            out_dir = work / "out"
            with st.spinner("판독·조회·판정 중... (문서 수에 따라 1~3분 소요)"):
                report = run_quality_review(
                    input_path,
                    out_dir,
                    today=today_str if isinstance(today_str, date) else date.today(),
                    max_pages=int(max_pages),
                )
            st.session_state["report"] = report

    report = st.session_state.get("report")
    if not report:
        st.info("서류를 업로드하고 '검토 실행'을 누르세요.")
        return

    products = report.get("products", [])
    order = {"적합": 1, "검토필요": 2, "부적합": 3}
    overall = max((p["overall"] for p in products), key=lambda v: order.get(v, 0), default="검토필요")
    st.markdown(f"## 전체 종합: {_verdict_badge(overall)}  ·  제품 {len(products)}개 · 파일 {len(report['files'])}개")

    # 환각으로 폐기된 추출값 안내(투명성)
    dropped = {
        Path(e.get("file", "")).name: e["_dropped_hallucinations"]
        for e in report["extractions"]
        if e.get("_dropped_hallucinations")
    }
    if dropped:
        with st.expander("⚠️ OCR 근거 없어 폐기한 값(환각 방지)"):
            for fn, d in dropped.items():
                st.caption(f"{fn}: {d}")

    unexpected = report.get("unexpected_files") or []
    if unexpected:
        msg = "⚠️ **zip에 예상 외/미상 파일이 있습니다** (확인 요망, 자동검토 제외)\n\n"
        msg += "\n".join(
            f"- {u['file']} (분류: {u.get('doc_type')}{', 오류: '+u['error'] if u.get('error') else ''})"
            for u in unexpected
        )
        st.warning(msg)

    for p in products:
        _render_product(p)

    with st.expander("📄 추출 원자료(문서별)"):
        for ext in report["extractions"]:
            st.markdown(f"**{Path(ext.get('file','')).name}** — `{ext.get('doc_type')}`")
            st.json(ext, expanded=False)

    st.download_button(
        "리포트 JSON 다운로드",
        json.dumps(report, ensure_ascii=False, indent=2),
        file_name="review_report.json",
        mime="application/json",
    )


def _render_product(p):
    st.divider()
    st.markdown(f"### 📦 {p.get('product') or '(제품명 미상)'} — {_verdict_badge(p['overall'])}")
    st.caption("인식 문서: " + (", ".join(p["documents_found"]) or "없음"))

    # 하이라이트: 확인 필요 / 미충족
    if p["flags"]:
        body = []
        for fl in p["flags"]:
            body.append(f"**[{fl['step']}] {fl['verdict']}**")
            body += [f"- {it}" for it in fl["items"]]
        text = "⚠️ **확인 필요 / 미충족 항목**\n\n" + "\n".join(body)
        (st.error if p["overall"] == "부적합" else st.warning)(text)
    else:
        st.success("✅ 모든 단계 적합 — 별도 확인 필요 항목 없음")

    steps = p["steps"]
    c1, c2, c3 = st.columns(3)
    _render_step1(c1, steps.get("step1_license", {}))
    _render_step2(c2, steps.get("step2_nutrition", {}))
    _render_step3(c3, steps.get("step3_self_quality", {}))


def _render_step1(col, s1):
    with col:
        st.subheader("1. 인허가 적합성")
        if "status" in s1:
            st.write(s1["status"])
            return
        v = s1.get("verdict", {})
        ev = s1.get("evidence", {})
        st.markdown(_verdict_badge(v.get("overall_verdict")))
        st.write(f"- 안전나라 DB 존재: {v.get('exists_in_db')} (근거 {v.get('db_match_basis','-')})")
        exact = ev.get("영업등록번호_정확매칭") or {}
        if exact:
            st.caption(f"매칭: {exact.get('업소명') or exact.get('business_name','')} · 영업등록 {exact.get('license_no','')}")
        st.write(f"- 표시사항 대조: {v.get('label_matches_license_doc')}")
        lv = ev.get("표시사항_검증") or {}
        if lv and "name_present" in lv:
            st.caption(f"라벨 비전검증 — 제조사명 {lv.get('name_present')} / 소재지 {lv.get('address_present')} (신뢰도 {lv.get('confidence','-')})")
        addr = (ev.get("주소_대조") or {}).get("인허가서류_vs_DB") or {}
        if addr:
            st.caption(f"주소대조(서류↔DB): {addr.get('match')} ({addr.get('basis')}, {addr.get('score')})")
        for r in v.get("reasons", []):
            st.caption(f"· {r}")


def _render_step2(col, s2):
    with col:
        st.subheader("2. 영양성분 비교")
        if "status" in s2:
            st.write(s2["status"])
            label = s2.get("표시사항_영양성분") or {}
            if label:
                st.caption("표시사항 영양성분(추출): " + ", ".join(f"{k}={v}" for k, v in label.items()))
            return
        st.markdown(_verdict_badge(s2.get("overall_verdict")))
        for c in s2.get("comparisons", []):
            st.write(f"- {c['name']}: {_VERDICT_COLOR.get(c['verdict'],'⚪')} {c['verdict']}")
            st.caption(c["detail"])


def _render_step3(col, s3):
    with col:
        st.subheader("3. 자가품질검사")
        if "status" in s3:
            st.write(s3["status"])
            return
        v = s3.get("verdict", {})
        ev = s3.get("evidence", {})
        st.markdown(_verdict_badge(v.get("overall_verdict")))
        agency = ev.get("검사기관_검증") or {}
        matched = agency.get("matched") or {}
        ag_icon = "🟢" if agency.get("found") else "🔴"
        st.write(f"- 검사기관 공인: {ag_icon} {agency.get('found')} (근거 {agency.get('match_basis','-')})")
        if matched:
            st.caption(f"{matched.get('name','')} · {matched.get('designation_no','')} · 지정유효 {matched.get('valid_until','-')}")
        else:
            st.caption(agency.get("detail", ""))
        validity = ev.get("유효기간") or {}
        vi = "🟢" if validity.get("valid") else ("🔴" if validity.get("valid") is False else "🟡")
        st.write(f"- 서류 유효기간: {vi} {'유효' if validity.get('valid') else ('만료' if validity.get('valid') is False else '확인필요')}")
        st.caption(validity.get("detail", ""))
        for it in v.get("items", []):
            st.write(f"- {it.get('name')}: {_VERDICT_COLOR.get(it.get('verdict'),'⚪')} {it.get('verdict')}")
            st.caption(it.get("reason", ""))
        if v.get("missing_required_items"):
            st.warning("누락 필수항목: " + ", ".join(v["missing_required_items"]))
        for r in v.get("reasons", []):
            st.caption(f"· {r}")


if __name__ == "__main__":
    main()
