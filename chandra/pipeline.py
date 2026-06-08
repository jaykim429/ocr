"""품질검토 파이프라인 오케스트레이터.

zip(또는 폴더/단일파일)을 입력받아:
  1) 압축 해제 → 파일 목록화
  2) 파일별 Gemma 판독·분류·필드추출 (chandra.extraction)
  3) 문서 종류에 따라 단계별 검토 자동 수행
       - 1단계: 인허가 적합성 (chandra.license_check)
       - 2단계: 영양성분 비교 (chandra.nutrition) — 영양성분성적서 제출 시
       - 3단계: 자가품질검사성적서 검토 (chandra.self_quality, 검사기관/유효기간 포함)
  4) 결과를 JSON + 마크다운 리포트로 저장

최종 적합성 '판단'은 각 단계에서 Gemma 가 수행한다.
"""

from __future__ import annotations

import json
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

from chandra.extraction import (
    DOC_LABEL,
    DOC_NUTRITION_CERT,
    DOC_PRODUCT_REPORT,
    DOC_SELF_QUALITY,
    DOC_UNKNOWN,
    classify_and_extract,
)
from chandra.license_check import LicenseCheckInput, check_license
from chandra.nutrition import compare_nutrition
from chandra.self_quality import (
    ManufactureReport,
    QualityCertificate,
    ReportTestItem,
    parse_results,
    review_self_quality_gemma,
)

_SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tiff", ".bmp", ".gif"}


def _gather_files(input_path: str | Path, work_dir: Path) -> list[Path]:
    """zip 이면 해제, 폴더면 순회, 단일 파일이면 그대로."""
    p = Path(input_path)
    if p.is_file() and p.suffix.lower() == ".zip":
        extract_dir = work_dir / "_unzipped"
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(p) as zf:
            zf.extractall(extract_dir)
        root: Path = extract_dir
    elif p.is_dir():
        root = p
    else:
        return [p] if p.suffix.lower() in _SUPPORTED else []

    files = [
        f
        for f in sorted(root.rglob("*"))
        if f.is_file() and f.suffix.lower() in _SUPPORTED
    ]
    return files


def _num(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    import re

    m = re.search(r"[-+]?\d[\d,]*\.?\d*", str(value))
    return float(m.group(0).replace(",", "")) if m else None


def _to_manufacture(ext: dict[str, Any] | None) -> ManufactureReport | None:
    if not ext:
        return None
    report_no = ext.get("manufacture_report_no")
    license_no = ext.get("license_no")
    # 영업등록번호 = 품목제조보고번호 앞 11자리 (보고번호 = 영업등록번호 + 품목순번)
    if not license_no and report_no and len(str(report_no)) >= 11:
        digits = "".join(ch for ch in str(report_no) if ch.isdigit())
        if len(digits) >= 11:
            license_no = digits[:11]
    return ManufactureReport(
        product_name=ext.get("product_name"),
        food_type=ext.get("food_type"),
        manufacture_report_no=report_no,
        business_name=ext.get("business_name"),
        license_no=license_no,
    )


def _to_certificate(ext: dict[str, Any] | None) -> QualityCertificate | None:
    if not ext:
        return None
    items = []
    for it in ext.get("test_items") or []:
        results_text = str(it.get("results") or "")
        items.append(
            ReportTestItem(
                name=it.get("name") or "",
                criteria_text=str(it.get("criteria") or ""),
                results_text=results_text,
                results=parse_results(results_text),
                judgement_text=str(it.get("judgement") or ""),
            )
        )
    return QualityCertificate(
        product_name=ext.get("product_name"),
        food_type=ext.get("food_type"),
        manufacture_report_no=ext.get("manufacture_report_no"),
        test_agency=ext.get("test_agency"),
        test_agency_designation_no=ext.get("test_agency_designation_no"),
        test_agency_tel=ext.get("test_agency_tel"),
        test_agency_address=ext.get("test_agency_address"),
        manufacturer=ext.get("business_name"),
        manufacturer_address=ext.get("address"),
        issue_date=ext.get("issue_date"),
        test_completed_date=ext.get("test_completed_date"),
        test_purpose=ext.get("test_purpose"),
        ingredients=ext.get("ingredients") or [],
        items=items,
        overall_text=ext.get("overall"),
    )


def _nutrition_map(ext: dict[str, Any] | None) -> dict[str, float | None]:
    if not ext:
        return {}
    nut = ext.get("nutrition") or {}
    return {k: _num(v) for k, v in nut.items() if v is not None}


_PRODUCT_DOC_TYPES = {DOC_PRODUCT_REPORT, DOC_SELF_QUALITY, DOC_LABEL, DOC_NUTRITION_CERT}


def _dedup_files(files: list[Path]) -> list[Path]:
    """내용 해시 기준 중복 파일 제거(워커힐처럼 같은 성적서가 여러 경로에 있는 경우)."""
    import hashlib

    seen: set[str] = set()
    out: list[Path] = []
    for f in files:
        try:
            h = hashlib.md5(f.read_bytes()).hexdigest()
        except Exception:  # noqa: BLE001
            out.append(f)
            continue
        if h in seen:
            continue
        seen.add(h)
        out.append(f)
    return out


def _report_no_key(ext: dict[str, Any]) -> str | None:
    """품목제조보고번호의 숫자 11자리 이상만 추출(제품 고유 식별자)."""
    rn = ext.get("manufacture_report_no")
    if not rn:
        return None
    digits = "".join(ch for ch in str(rn) if ch.isdigit())
    return digits if len(digits) >= 11 else None


def _group_by_product(extractions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """추출 결과를 같은 제품끼리 묶는다(다제품 zip 대응).

    OCR 로 제품명이 문서마다 다르게 읽힐 수 있으므로(예: 워커힐↔위커협),
    품목제조보고번호(11자리)가 같으면 우선 동일 제품으로 묶고, 없으면 제품명 유사도로 묶는다.
    """
    from chandra.text_match import collapse, ratio

    docs = [e for e in extractions if e.get("doc_type") in _PRODUCT_DOC_TYPES]
    # 식별키(보고번호 또는 제품명)가 있는 문서로 클러스터 형성, 둘 다 없는 문서는 floating
    keyed = [e for e in docs if _report_no_key(e) or collapse(e.get("product_name"))]
    floating = [e for e in docs if not _report_no_key(e) and not collapse(e.get("product_name"))]
    # 강한 키(보고번호) 있는 문서를 먼저 배치 → 이름만 있는 문서가 거기에 붙도록
    ordered = sorted(keyed, key=lambda e: 0 if _report_no_key(e) else 1)

    clusters: list[dict[str, Any]] = []
    for e in ordered:
        pn = collapse(e.get("product_name"))
        rn = _report_no_key(e)
        target = None
        # 1) 보고번호(강한 키) 일치 = 동일 제품(이름 달라도)
        if rn:
            target = next((c for c in clusters if rn in c["report_nos"]), None)
        # 2) 이름 유사도: 첫 매칭이 아니라 '가장 잘 맞는' 클러스터를 고른다.
        #    부분 포함은 짧은 이름의 오결합(예: '한과'⊂'전통한과세트')을 막기 위해
        #    양쪽 길이 4자 이상일 때만 인정한다.
        if target is None and pn:
            best, best_s = None, 0.0
            for c in clusters:
                if not c["key"]:
                    continue
                s = ratio(pn, c["key"])
                if (pn == c["key"] or pn in c["key"] or c["key"] in pn) and min(len(pn), len(c["key"])) >= 4:
                    s = max(s, 0.9)
                if s > best_s:
                    best, best_s = c, s
            if best is not None and best_s >= 0.7:
                target = best
        if target is None:
            target = {"key": pn, "name": e.get("product_name"), "report_nos": set(), "docs": []}
            clusters.append(target)
        target["docs"].append(e)
        if rn:
            target["report_nos"].add(rn)
        if not target["key"] and pn:  # 무명으로 만든 클러스터에 이름이 생기면 채움
            target["key"], target["name"] = pn, e.get("product_name")

    if not clusters:
        clusters = [{"key": "", "name": None, "report_nos": set(), "docs": []}]
    if len(clusters) == 1:
        clusters[0]["docs"].extend(floating)  # 단일 제품 → 이름없는 문서(표시사항 등)도 합침
        return clusters

    # 다제품: 이름·보고번호가 안 읽힌 표시사항 등은 '소재지(공장주소)'로 매칭해 붙인다.
    # 같은 주소 클러스터가 여럿이면, 아직 그 문서종류(예: 표시사항)가 없는 클러스터를 우선.
    def _addr_key(e: dict[str, Any]) -> str:
        return collapse(e.get("address"))  # 전체 정규화 주소(부분 prefix 오결합 방지)

    def _addr_hit(ak: str, addrs: set[str]) -> bool:
        # 도+시군구 수준의 짧은 공통 prefix 오결합을 막기 위해 겹치는 길이가 12자 이상일 때만 인정.
        return any((ak in a or a in ak) and min(len(ak), len(a)) >= 12 for a in addrs)

    cluster_addrs = [{_addr_key(d) for d in c["docs"] if _addr_key(d)} for c in clusters]
    leftover: list[dict[str, Any]] = []
    for e in floating:
        ak = _addr_key(e)
        cand = [i for i, addrs in enumerate(cluster_addrs) if ak and _addr_hit(ak, addrs)]
        if not cand:
            leftover.append(e)
            continue
        dt = e.get("doc_type")
        # 해당 문서종류가 아직 없는 클러스터 우선(라벨 없는 제품에 라벨을 붙이기)
        cand.sort(key=lambda i: any(d.get("doc_type") == dt for d in clusters[i]["docs"]))
        clusters[cand[0]]["docs"].append(e)
    if leftover:
        clusters.append({"key": "", "name": "(제품 미상)", "report_nos": set(), "docs": leftover})
    return _merge_complementary_clusters(clusters)


def _merge_complementary_clusters(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """같은 업체·주소인데 보고번호/제품명만 OCR 수준으로 다르고 문서종류가 상호배타(보완)인
    클러스터를 1제품으로 병합한다(예: 성적서만 있는 고아 클러스터 + 보고서·라벨 클러스터).

    '문서종류 상호배타'를 요구해, 같은 공장의 진짜 다른 SKU(양쪽 다 보고서를 가짐)는 합치지 않는다.
    병합 시 보고번호·제품명 불일치를 doc_mismatch 로 남겨 검토필요로 노출한다.
    """
    from chandra.address import _edit_distance, normalize_address
    from chandra.text_match import collapse, ratio

    def biz(c):
        return {collapse(d.get("business_name")) for d in c["docs"] if collapse(d.get("business_name"))}

    def addrs(c):
        return {normalize_address(d.get("address")) for d in c["docs"] if normalize_address(d.get("address"))}

    def dtypes(c):
        return {d.get("doc_type") for d in c["docs"]}

    def report_nos(c):
        return {r for d in c["docs"] if (r := _report_no_key(d))}

    def names(c):
        return {collapse(d.get("product_name")) for d in c["docs"] if collapse(d.get("product_name"))}

    def addr_close(a: set[str], b: set[str]) -> bool:
        return any(x == y or (min(len(x), len(y)) >= 12 and _edit_distance(x, y) <= 2) for x in a for y in b)

    def merge_score(a, b) -> float | None:
        """병합해도 되면 점수(높을수록 잘 맞음), 아니면 None."""
        if dtypes(a) & dtypes(b):  # 핵심 안전장치: 문서종류가 겹치면 서로 다른 제품으로 본다
            return None
        if not addr_close(addrs(a), addrs(b)):  # 주소(공장)가 같아야 함
            return None
        ra, rb = report_nos(a), report_nos(b)
        rn_dist = min((_edit_distance(x, y) for x in ra for y in rb), default=99) if (ra and rb) else 99
        nm_sim = max((ratio(x, y) for x in names(a) for y in names(b)), default=0.0) if (names(a) and names(b)) else 0.0
        # 보고번호 OCR 근접(편집거리≤1)이 주신호. 제품명만으로 합칠 땐 매우 높은 유사도(≥0.85)를 요구
        # 한다(같은 공장의 다른 제품을 느슨한 이름 유사도로 오병합하지 않도록).
        if rn_dist <= 1 or nm_sim >= 0.85:
            return (10 - rn_dist) + nm_sim  # 보고번호 거리 작을수록, 이름 유사할수록 우선
        return None

    clusters = [dict(c) for c in clusters]
    out: list[dict[str, Any]] = []
    for c in clusters:
        # 여러 후보 중 '가장 잘 맞는' 클러스터로 병합(보고번호 거리·이름 유사도 기준).
        scored = [(s, o) for o in out if (s := merge_score(o, c)) is not None]
        tgt = max(scored, key=lambda t: t[0])[1] if scored else None
        if tgt is None:
            out.append(c)
            continue
        # 병합: 문서 합치고 보고번호·제품명 불일치 기록
        mismatch = tgt.get("doc_mismatch") or {}
        rns = report_nos(tgt) | report_nos(c)
        nms = {d.get("product_name") for d in (tgt["docs"] + c["docs"]) if d.get("product_name")}
        if len(rns) > 1:
            mismatch["품목제조보고번호"] = sorted(rns)
        # 제품명은 OCR 변이(예: '뼈를'↔'뼈클'↔'뼈름')로 서로 달라 보일 뿐인 경우가 많다.
        # 이름들이 서로 충분히 유사하면(OCR 차이 수준) 불일치로 띄우지 않고, 명백히 다른 이름이
        # 섞였을 때만 기록한다(가장 동떨어진 한 쌍의 유사도가 낮을 때).
        if len(nms) > 1:
            nlist = sorted(nms)
            min_sim = min(ratio(collapse(a), collapse(b)) for i, a in enumerate(nlist) for b in nlist[i + 1:])
            if min_sim < 0.6:
                mismatch["제품명"] = nlist
        tgt["docs"] = tgt["docs"] + c["docs"]
        tgt["report_nos"] = set(tgt.get("report_nos") or set()) | set(c.get("report_nos") or set())
        if not tgt.get("key") and c.get("key"):
            tgt["key"], tgt["name"] = c["key"], c.get("name")
        if mismatch:
            tgt["doc_mismatch"] = mismatch
    return out


def _run_steps_for_product(
    docs: list[dict[str, Any]], today: date | None
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """한 제품의 문서들로 1·2·3단계를 수행한다."""
    by_type: dict[str, dict[str, Any]] = {}
    for ext in docs:
        dt = ext.get("doc_type", "기타")
        if dt not in by_type:
            by_type[dt] = ext
            continue
        # 같은 종류 문서가 둘 이상이면(병합 업로드 등) 첫 문서만 쓰고 나머지를 버리지 말고,
        # 리스트 필드(시험항목·원재료)를 합쳐 누락을 방지한다(스칼라 필드는 첫 문서 유지).
        primary = by_type[dt] = dict(by_type[dt])  # 공유 추출 dict 변형 방지용 복사
        for lf in ("test_items", "ingredients"):
            merged = list(primary.get(lf) or [])
            for x in (ext.get(lf) or []):
                if x not in merged:
                    merged.append(x)
            if merged:
                primary[lf] = merged
        primary["_merged_duplicates"] = primary.get("_merged_duplicates", 1) + 1

    mfr = _to_manufacture(by_type.get(DOC_PRODUCT_REPORT))
    cert = _to_certificate(by_type.get(DOC_SELF_QUALITY))
    labels = [d for d in docs if d.get("doc_type") == DOC_LABEL]  # 한 제품에 표시사항이 여러 개일 수 있음
    label_ext = labels[0] if labels else None
    nutri_ext = by_type.get(DOC_NUTRITION_CERT)
    steps: dict[str, Any] = {}

    # 1·2·3단계는 서로 독립(다른 문서·다른 판정) → 모델 호출을 병렬로 수행해 시간 단축
    def _step1() -> dict[str, Any]:
        return _run_step1(by_type, mfr, labels)

    def _step2() -> dict[str, Any]:
        from chandra.nutrition import nutrition_reference

        label_nutri = _nutrition_map(label_ext)
        measured_nutri = _nutrition_map(nutri_ext)
        basis = (label_ext or {}).get("nutrition_basis")
        ft = _resolve_food_type(by_type).get("value")
        # 식품유형 대비 영양성분 한 줄 참고 코멘트(판정 아님)
        ref_note = nutrition_reference(ft, label_nutri, basis=basis) if label_nutri else None
        if label_nutri and measured_nutri:
            out = compare_nutrition(label_nutri, measured_nutri).to_dict()
            out["표시기준단위"] = basis
            out["식품유형_참고"] = ref_note
            return out
        return {
            "status": "영양성분성적서 미제출 또는 표시사항 영양성분 미추출 - 비교 로직 준비됨",
            "표시기준단위": basis,
            "표시사항_영양성분": label_nutri,
            "성적서_실측": measured_nutri,
            "식품유형_참고": ref_note,
        }

    def _step3() -> dict[str, Any]:
        if cert:
            label_list = [
                {"product_name": e.get("product_name"), "business_name": e.get("business_name"), "address": e.get("address")}
                for e in labels
            ]
            # 원재료(보고서·라벨·성적서)를 모아 '사용 첨가물' 판단 근거로 — 미사용 첨가물 검사항목은 누락 아님
            ing: list[str] = []
            for d in (by_type.get(DOC_PRODUCT_REPORT), *labels, by_type.get(DOC_SELF_QUALITY)):
                for x in (d or {}).get("ingredients") or []:
                    if x and x not in ing:
                        ing.append(x)
            # 품목특성(살균구분·영양표시의무 등) — 멸균제품 대장균군 면제 등 판정에 사용
            traits = (by_type.get(DOC_PRODUCT_REPORT) or {}).get("product_traits") or None
            return review_self_quality_gemma(
                cert, manufacture=mfr, today=today, labels=label_list,
                ingredients=ing, product_traits=traits,
            )
        return {"status": "건너뜀 (자가품질검사성적서 없음)"}

    def _step4() -> dict[str, Any]:
        from chandra.address import label_address_discrepancy
        from chandra.label_check import review_label_disclosures

        if not label_ext:
            return {"status": "건너뜀 (표시사항 없음)"}
        ft = _resolve_food_type(by_type).get("value")
        official_addr = (by_type.get(DOC_PRODUCT_REPORT) or {}).get("address") or (mfr.address if mfr else None)
        res = review_label_disclosures(label_ext, food_type=ft, official_address=official_addr)

        # 표시사항 주소가 공식(품목제조보고서) 주소와 다르면 자동 '적합' 통과 금지 — 반드시 검토 표시.
        addr_issues = [d for lab in labels
                       if (d := label_address_discrepancy(lab.get("address"), official_addr))]
        if addr_issues:
            v = res.setdefault("verdict", {}) or res["verdict"]
            res["verdict"] = v
            res.setdefault("evidence", {})["주소_불일치"] = addr_issues
            v.setdefault("items", []).insert(0, {
                "name": "생산자(영업소) 소재지 표시",
                "verdict": "검토필요",
                "reason": addr_issues[0]["detail"],
            })
            for d in addr_issues:
                v.setdefault("reasons", []).append("표시사항 소재지 오기 의심: " + d["detail"])
            if v.get("overall_verdict") in (None, "적합"):
                v["overall_verdict"] = "검토필요"
        return res

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=4) as ex:
        f1, f2, f3, f4 = ex.submit(_step1), ex.submit(_step2), ex.submit(_step3), ex.submit(_step4)
        steps["step1_license"] = f1.result()
        steps["step2_nutrition"] = f2.result()
        steps["step3_self_quality"] = f3.result()
        steps["step4_label"] = f4.result()
    return by_type, steps


def _run_step1(by_type: dict[str, Any], mfr: Any, labels: list[dict[str, Any]]) -> dict[str, Any]:
    """1단계: 인허가 적합성. 표시사항이 여러 개면 각각 검증한다."""
    labels = labels or []
    label_ext = labels[0] if labels else None
    if not (mfr or label_ext):
        return {"status": "건너뜀 (품목제조보고서/표시사항 없음)"}

    ref_address = (by_type.get(DOC_PRODUCT_REPORT) or {}).get("address")
    ref_name = mfr.business_name if mfr else None

    # 표시사항별로 이미지 비전 검증(저해상 라벨도 기준값 존재여부는 정확)
    label_infos: list[dict[str, Any]] = []
    if mfr or ref_address:
        from chandra.extraction import render_file, render_tiles
        from chandra.license_check import verify_label_against_reference

        for idx, lab in enumerate(labels):
            verification = None
            if lab.get("file"):
                try:
                    imgs = render_file(lab["file"], max_pages=1, target_long_side=3200)
                    vimgs = list(imgs)
                    for img in imgs[:1]:
                        vimgs.extend(render_tiles(img, grid=(2, 2)))
                    verification = verify_label_against_reference(vimgs[:5], ref_name=ref_name, ref_address=ref_address)
                except Exception:  # noqa: BLE001
                    verification = None
            label_infos.append({
                "index": idx + 1,
                "business_name": lab.get("business_name"),
                "address": lab.get("address"),
                "product_name": lab.get("product_name"),
                "verification": verification,
            })

    lic_input = LicenseCheckInput(
        business_name=ref_name,
        license_no=mfr.license_no if mfr else None,
        address=ref_address,
        representative=(by_type.get(DOC_PRODUCT_REPORT) or {}).get("representative"),
        label_business_name=(label_ext or {}).get("business_name"),
        label_address=(label_ext or {}).get("address"),
        label_verification=label_infos[0]["verification"] if label_infos else None,
        labels=label_infos,
    )
    return check_license(lic_input).to_dict()


def collect_flags(steps: dict[str, Any]) -> list[dict[str, Any]]:
    """단계별 결과에서 '미충족(부적합)/확인필요' 항목만 추려 하이라이트용으로 반환."""
    flags: list[dict[str, Any]] = []

    s1 = steps.get("step1_license", {})
    v1 = s1.get("verdict")
    if v1 and v1.get("overall_verdict") != "적합":
        flags.append({"step": "1. 인허가", "verdict": v1.get("overall_verdict"), "items": list(v1.get("reasons", []))})

    s2 = steps.get("step2_nutrition", {})
    if "comparisons" in s2:
        bad = [f"{c['name']}: {c['detail']}" for c in s2["comparisons"] if c.get("verdict") != "적합"]
        if bad:
            flags.append({"step": "2. 영양성분", "verdict": s2.get("overall_verdict"), "items": bad})

    s3 = steps.get("step3_self_quality", {})
    v3 = s3.get("verdict")
    if v3 and v3.get("overall_verdict") != "적합":
        items = [f"{it.get('name')}: {it.get('verdict')} — {it.get('reason')}"
                 for it in v3.get("items", []) if it.get("verdict") != "적합"]
        items += [f"누락 필수항목: {m}" for m in v3.get("missing_required_items", [])]
        ev3 = s3.get("evidence", {})
        ag = (ev3.get("검사기관_검증") or {})
        # 영업자 직접 자가품질검사(검사기관=제조사)는 공인 위탁목록 미존재가 흠이 아님
        if ag and not ag.get("found") and not ev3.get("검사기관_제조사동일_자체검사"):
            items.append(f"검사기관 미확인: {ag.get('detail')}")
        if ag.get("designation_expired"):
            items.append(f"검사기관 지정 만료: {ag.get('detail')}")
        val = (ev3.get("유효기간") or {})
        if val.get("valid") is False:
            items.append(f"유효기간 만료: {val.get('detail')}")
        flags.append({"step": "3. 자가품질", "verdict": v3.get("overall_verdict"), "items": items})

    s4 = steps.get("step4_label", {})
    v4 = s4.get("verdict")
    if v4 and v4.get("overall_verdict") != "적합":
        items = [f"{it.get('name')}: {it.get('reason')}"
                 for it in v4.get("items", []) if it.get("verdict") != "적합"]
        items += [f"누락 표시항목: {m}" for m in v4.get("missing_required_items", [])]
        flags.append({"step": "4. 표시사항", "verdict": v4.get("overall_verdict"), "items": items})

    return flags


def _product_overall(steps: dict[str, Any]) -> str:
    order = {"부적합": 3, "검토필요": 2, "적합": 1}
    worst, rank = "적합", 0
    found = False
    for s in steps.values():
        v = (s.get("verdict", {}) or {}).get("overall_verdict") or s.get("overall_verdict")
        if v in order:
            found = True
            if order[v] > rank:
                worst, rank = v, order[v]
    return worst if found else "검토필요"


def _resolve_food_type(by_type: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """식품유형을 출처 우선순위로 확정하고 오류 신호를 함께 낸다.

    원칙(오류 최소화):
      1) 출처 우선순위 = 품목제조보고서 > 자가품질성적서 > 영양성분성적서 > 표시사항(라벨)
         (텍스트레이어 서류가 스캔 라벨 OCR 보다 정확)
      2) 문서 간 식품유형 표기가 다르면 mismatch=True (담당자 확인용)
      3) 확정값이 식품공전(I0930)에 정확히 등록된 표기인지 검증(registered)
    반환: {value, source, candidates, mismatch, registered}
    """
    from chandra.text_match import collapse

    from collections import Counter

    pref = [DOC_PRODUCT_REPORT, DOC_SELF_QUALITY, DOC_NUTRITION_CERT, DOC_LABEL]
    cands = [(dt, (by_type.get(dt) or {}).get("food_type", "").strip())
             for dt in pref if (by_type.get(dt) or {}).get("food_type")]
    if not cands:
        return {"value": None, "source": None, "candidates": [], "mismatch": False, "registered": None}
    value, source = cands[0][1], cands[0][0]
    mismatch = len({collapse(v) for _, v in cands}) > 1

    def _registered(v: str) -> bool | None:
        try:
            from chandra.foodsafety import search_food_spec

            rows = search_food_spec(v)
            return any((r.get("product_type") or "").strip() == v for r in rows)
        except Exception:  # noqa: BLE001
            return None

    registered = _registered(value)
    consensus_override = False
    # 다른 서류 2개 이상이 같은 표기로 합의했는데 최우선(보고서) 단독값이 그와 다르면 합의값을
    # 채택한다. 보고서의 '품목의 유형'이 안내문구('주원료의 유형(식육간편조리세트의 경우만…)')와
    # 혼동돼 오추출되는 사례가 있어, 독립 서류 2건의 합의를 단독값보다 신뢰한다(보고서 값이 식품공전에
    # 등록된 표기여도 적용). mismatch 경고는 그대로 노출돼 담당자가 확인한다.
    if mismatch:
        counts = Counter(collapse(v) for _, v in cands)
        best_norm, best_n = counts.most_common(1)[0]
        if best_n >= 2 and best_n > counts[collapse(value)]:
            for d, v in cands:
                if collapse(v) == best_norm:
                    value, source, consensus_override = v, d, True
                    registered = _registered(value)
                    break

    return {
        "value": value, "source": source,
        "candidates": [{"doc": d, "food_type": v} for d, v in cands],
        "mismatch": mismatch, "registered": registered,
        "consensus_override": consensus_override,
    }


def _amendment_check(by_type: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """품목제조보고사항 변경보고서(시행규칙 제46조) 안내·교차검증.

    변경보고서면 '변경 후(최신) 기준' 안내를 띄우고, 자가품질성적서 발급일이 변경보고일보다
    이전이면 성적서가 변경 전 기준일 수 있어 검토필요로 격상한다.
    """
    rep = by_type.get(DOC_PRODUCT_REPORT) or {}
    if not rep.get("is_amendment"):
        return None
    from chandra.validity import parse_date

    changes = rep.get("amendment_changes") or []
    items = [
        "📝 품목제조보고사항 변경보고서 — '변경 후(최신)' 내용이 기준입니다(시행규칙 제46조). "
        f"변경 항목: {', '.join(changes) if changes else '확인 필요'}. "
        "자가품질성적서·표시사항·상세페이지가 최신 기준과 일치하는지 확인하세요."
    ]
    cert = by_type.get(DOC_SELF_QUALITY) or {}
    adate, idate = parse_date(rep.get("amendment_date")), parse_date(cert.get("issue_date"))
    stale = bool(adate and idate and idate < adate)
    if stale:
        items.append(
            f"⚠ 성적서 발급일({idate.isoformat()})이 변경보고일({adate.isoformat()})보다 이전 — "
            "성적서가 변경 전 원재료·기준으로 발급됐을 수 있어 재확인 필요"
        )
    return {"step": "변경보고서", "verdict": "검토필요" if stale else "안내", "items": items, "stale": stale}


def _basic_info(by_type: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """제품 기본 정보(제품명·식품유형·영업소 등)를 문서 우선순위로 집계.

    담당자가 업로드 직후 추출 정확성을 표로 즉시 확인하기 위한 요약.
    각 항목의 출처 문서를 함께 표기한다.
    """
    # 필드별 우선순위 문서
    order = {
        "제품명": ("product_name", [DOC_PRODUCT_REPORT, DOC_LABEL, DOC_SELF_QUALITY, DOC_NUTRITION_CERT]),
        "식품유형": ("food_type", [DOC_PRODUCT_REPORT, DOC_SELF_QUALITY, DOC_LABEL]),
        "영업자(제조원)": ("business_name", [DOC_PRODUCT_REPORT, DOC_SELF_QUALITY, DOC_LABEL]),
        "영업등록번호": ("license_no", [DOC_PRODUCT_REPORT, DOC_LABEL]),
        "품목제조보고번호": ("manufacture_report_no", [DOC_PRODUCT_REPORT, DOC_SELF_QUALITY]),
        "소재지": ("address", [DOC_PRODUCT_REPORT, DOC_LABEL, DOC_SELF_QUALITY]),
        "대표자": ("representative", [DOC_PRODUCT_REPORT]),
    }
    ft = _resolve_food_type(by_type)
    rows = []
    for label, (key, doc_pref) in order.items():
        if key == "food_type":
            rows.append({"field": label, "value": ft["value"], "source": ft["source"]})
            continue
        value, source = None, None
        for dt in doc_pref:
            ext = by_type.get(dt)
            if ext and ext.get(key):
                value, source = ext.get(key), dt
                break
        rows.append({"field": label, "value": value, "source": source})
    return rows


def run_quality_review(
    input_path: str | Path,
    out_dir: str | Path,
    today: date | None = None,
    max_pages: int = 6,
    on_progress: Any = None,
) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    def _progress(text: str) -> None:
        if on_progress:
            try:
                on_progress(text)
            except Exception:  # noqa: BLE001 - 진행표시 실패는 검토에 영향 없음
                pass

    files = _dedup_files(_gather_files(input_path, out))
    _progress(f"제출 서류 판독 중 (총 {len(files)}건)")

    def _extract_one(f: Path) -> list[dict[str, Any]]:
        # 이미지(스캔/라벨)는 작은 글씨가 많아 처음부터 타일 확대 패스로 1회 처리(Gemma 호출 절감).
        # 텍스트레이어 PDF 는 타일 불필요. 한 파일에 여러 제품(병합 PDF)이면 제품별로 분리됨.
        is_image = f.suffix.lower() != ".pdf"
        exts = classify_and_extract(str(f), max_pages=max_pages, tile=is_image)
        if len(exts) == 1 and exts[0].get("doc_type") == DOC_LABEL and not is_image:
            exts = classify_and_extract(str(f), max_pages=max_pages, tile=True)
        return exts

    # 파일별 판독은 서로 독립 → 병렬 처리로 단일 검토 속도 향상 (파일당 결과 리스트를 평탄화)
    if len(files) > 1:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=min(6, len(files))) as ex:
            nested = list(ex.map(_extract_one, files))
    else:
        nested = [_extract_one(f) for f in files]
    extractions = [e for sub in nested for e in sub]

    clusters = _group_by_product(extractions)
    products: list[dict[str, Any]] = []
    for idx, cluster in enumerate(clusters, 1):
        nm = cluster.get("name") or "제품"
        _progress(f"품질 검토 중: {nm} (인허가·영양성분·자가품질·표시사항) — {idx}/{len(clusters)}")
        by_type, steps = _run_steps_for_product(cluster["docs"], today)
        overall = _product_overall(steps)
        flags = collect_flags(steps)
        # 동일 업체·주소로 묶였으나 보고번호·제품명이 서류 간 불일치(OCR 오류 또는 다른 제품 서류 혼입)
        mismatch = cluster.get("doc_mismatch")
        if mismatch:
            items = [f"{k} 불일치: {' / '.join(map(str, v))}" for k, v in mismatch.items()]
            flags.insert(0, {"step": "서류 일관성", "verdict": "검토필요",
                             "items": ["동일 업체·주소 서류로 묶였으나 식별정보가 다릅니다 — 같은 제품의 "
                                       "서류 오류이거나 다른 제품 서류가 섞였을 수 있어 확인 필요"] + items})
            if overall == "적합":
                overall = "검토필요"
        # 변경보고서(시행규칙 제46조) 안내 + 성적서 변경 전 발급 여부 검토
        amend = _amendment_check(by_type)
        if amend:
            flags.insert(0, {"step": amend["step"], "verdict": amend["verdict"], "items": amend["items"]})
            if amend["stale"] and overall == "적합":
                overall = "검토필요"
        products.append({
            "product": cluster.get("name") or (by_type.get(DOC_LABEL, {}) or {}).get("product_name"),
            "basic_info": _basic_info(by_type),
            "food_type_check": _resolve_food_type(by_type),
            "documents_found": list(by_type.keys()),
            "overall": overall,
            "doc_mismatch": mismatch,
            "flags": flags,
            "steps": steps,
        })

    # 예상 외/미상 파일(특허증 등 분류 불가) → 처리하지 않고 알림만
    unexpected = [
        {"file": Path(e.get("file", "")).name, "doc_type": e.get("doc_type"), "error": e.get("error")}
        for e in extractions
        if e.get("doc_type") == DOC_UNKNOWN or e.get("error")
    ]

    _progress("종합 판정 정리 중")
    report = {
        "input": str(input_path),
        "files": [str(f) for f in files],
        "extractions": extractions,
        "products": products,
        "unexpected_files": unexpected,
    }
    (out / "review_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "review_report.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def run_quality_review_batch(
    inputs: list[str | Path],
    out_dir: str | Path,
    today: date | None = None,
    max_pages: int = 6,
    max_workers: int = 4,
    on_progress: Any = None,
) -> dict[str, Any]:
    """여러 검토대상(zip 등)을 병렬로 각각 판정해 units 로 묶는다(zip 1개 = 검토단위 1개).

    단일 입력도 units 길이 1로 통일해 반환한다.
    """
    from concurrent.futures import ThreadPoolExecutor

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    inputs = [Path(p) for p in inputs]
    _multi = len(inputs) > 1

    def one(idx: int, p: Path) -> dict[str, Any]:
        sub = out / f"unit{idx}_{p.stem}"
        # 검토단위가 여러 개면 단위별 진행표시에 단위명을 접두로 붙인다.
        unit_cb = None
        if on_progress:
            unit_cb = (lambda t, _n=p.stem: on_progress(f"[{_n}] {t}")) if _multi else on_progress
        try:
            rep = run_quality_review(p, sub, today=today, max_pages=max_pages, on_progress=unit_cb)
            return {"name": p.stem, "input": str(p), **rep}
        except Exception as exc:  # noqa: BLE001 - 한 건 실패가 전체를 막지 않도록
            return {"name": p.stem, "input": str(p), "error": str(exc),
                    "products": [], "files": [], "extractions": [], "unexpected_files": []}

    with ThreadPoolExecutor(max_workers=min(max_workers, len(inputs))) as ex:
        units = list(ex.map(lambda t: one(*t), list(enumerate(inputs))))

    report = {"units": units, "multi": len(units) > 1}
    (out / "review_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


_ICON = {"적합": "🟢", "부적합": "🔴", "검토필요": "🟡", "판정불가": "⚪"}


def _render_product_md(p: dict[str, Any]) -> list[str]:
    lines = [f"## 📦 {p.get('product') or '(제품명 미상)'} — {_ICON.get(p['overall'],'⚪')} **{p['overall']}**", ""]
    lines.append(f"- 인식 문서: {', '.join(p['documents_found']) or '없음'}")

    # 하이라이트: 확인 필요/미충족
    if p["flags"]:
        lines += ["", "> ⚠️ **확인 필요 / 미충족 항목**"]
        for fl in p["flags"]:
            lines.append(f"> - **[{fl['step']}] {_ICON.get(fl['verdict'],'⚠️')} {fl['verdict']}**")
            for it in fl["items"]:
                lines.append(f">   - {it}")
    else:
        lines += ["", "> ✅ 모든 단계 적합 — 별도 확인 필요 항목 없음"]
    lines.append("")

    steps = p["steps"]
    s1 = steps.get("step1_license", {})
    v1 = s1.get("verdict", {})
    lines.append("### 1단계 · 인허가 적합성")
    if "status" in s1:
        lines.append(f"- {s1['status']}")
    else:
        lines.append(f"- {_ICON.get(v1.get('overall_verdict'),'⚪')} **{v1.get('overall_verdict','?')}** "
                      f"· DB 존재 {v1.get('exists_in_db')} · 표시사항 대조 {v1.get('label_matches_license_doc')}")
        for r in v1.get("reasons", []):
            lines.append(f"  - {r}")

    s2 = steps.get("step2_nutrition", {})
    lines.append("### 2단계 · 영양성분 비교")
    if "status" in s2:
        lines.append(f"- {s2['status']}")
    else:
        lines.append(f"- {_ICON.get(s2.get('overall_verdict'),'⚪')} **{s2.get('overall_verdict','?')}**")
        for c in s2.get("comparisons", []):
            lines.append(f"  - {_ICON.get(c['verdict'],'⚪')} {c['name']}: {c['detail']}")

    s3 = steps.get("step3_self_quality", {})
    lines.append("### 3단계 · 자가품질검사")
    if "status" in s3:
        lines.append(f"- {s3['status']}")
    else:
        v3 = s3.get("verdict", {})
        ev3 = s3.get("evidence", {})
        agency = ev3.get("검사기관_검증") or {}
        validity = ev3.get("유효기간") or {}
        lines.append(f"- {_ICON.get(v3.get('overall_verdict'),'⚪')} **{v3.get('overall_verdict','?')}**")
        lines.append(f"  - 검사기관 공인: {'🟢' if agency.get('found') else '🔴'} {agency.get('detail')}")
        lines.append(f"  - 유효기간: {'🟢' if validity.get('valid') else '🔴'} {validity.get('detail')}")
        for it in v3.get("items", []):
            lines.append(f"  - {_ICON.get(it.get('verdict'),'⚪')} {it.get('name')}: {it.get('reason')}")
        if v3.get("missing_required_items"):
            lines.append(f"  - ⚠️ 누락 필수항목: {', '.join(v3['missing_required_items'])}")
    lines.append("")
    return lines


def render_markdown(report: dict[str, Any]) -> str:
    products = report.get("products", [])
    worst = "적합"
    order = {"적합": 1, "검토필요": 2, "부적합": 3}
    for p in products:
        if order.get(p["overall"], 0) > order.get(worst, 0):
            worst = p["overall"]
    lines = ["# 품질검토 자동 리포트", ""]
    lines.append(f"- 입력: {report['input']}")
    lines.append(f"- 파일 수: {len(report['files'])} · 제품 수: {len(products)}")
    lines.append(f"- **전체 종합: {_ICON.get(worst,'⚪')} {worst}**")
    lines.append("")
    unexpected = report.get("unexpected_files") or []
    if unexpected:
        lines += ["> ⚠️ **zip에 예상 외/미상 파일이 있습니다 (확인 요망, 자동검토 제외)**"]
        for u in unexpected:
            lines.append(f">  - {u['file']} (분류: {u.get('doc_type')}{', 오류: '+u['error'] if u.get('error') else ''})")
        lines.append("")
    for p in products:
        lines += _render_product_md(p)
    return "\n".join(lines)
