"""신규 QA 기능 회귀테스트 — 순수 로직(네트워크/Gemma 불필요).

다제품 그룹핑, 식품유형 합의, 기본정보 출처우선, 자가품질 검사주기,
고시 첨부 파서 유틸, 잡 영속화(SQLite)를 검증한다.
"""
from __future__ import annotations

import io
import zipfile

import pytest

from chandra.extraction import DOC_LABEL, DOC_NUTRITION_CERT, DOC_PRODUCT_REPORT, DOC_SELF_QUALITY


# ---------------------------------------------------------------------------
# 다제품 그룹핑 (_group_by_product)
# ---------------------------------------------------------------------------
def test_group_single_product_absorbs_unnamed_label():
    from chandra.pipeline import _group_by_product

    ext = [
        {"doc_type": DOC_PRODUCT_REPORT, "product_name": "인생 촉촉 노가리", "manufacture_report_no": "20210488859"},
        {"doc_type": DOC_SELF_QUALITY, "product_name": "인생촉촉노가리"},
        {"doc_type": DOC_LABEL, "product_name": None},  # 이름 없는 표시사항
    ]
    cl = _group_by_product(ext)
    assert len(cl) == 1
    assert len(cl[0]["docs"]) == 3


def test_group_by_report_no_when_names_differ():
    """OCR 로 제품명이 달라도 품목보고번호가 같으면 한 제품."""
    from chandra.pipeline import _group_by_product

    ext = [
        {"doc_type": DOC_PRODUCT_REPORT, "product_name": "워커힐 폭립", "manufacture_report_no": "20200397042001"},
        {"doc_type": DOC_SELF_QUALITY, "product_name": "위커협 폭립", "manufacture_report_no": "20200397042001"},
    ]
    cl = _group_by_product(ext)
    assert len(cl) == 1


def test_group_merged_two_products_split_by_report_no():
    """병합 PDF 다제품: 보고번호가 다르면 분리."""
    from chandra.pipeline import _group_by_product

    ext = [
        {"doc_type": DOC_PRODUCT_REPORT, "product_name": "정읍쌍화차", "manufacture_report_no": "202206873501"},
        {"doc_type": DOC_SELF_QUALITY, "product_name": "정읍쌍화차", "manufacture_report_no": "202206873501"},
        {"doc_type": DOC_PRODUCT_REPORT, "product_name": "쌍화밤고명", "manufacture_report_no": "202206873507"},
        {"doc_type": DOC_SELF_QUALITY, "product_name": "쌍화밤고명", "manufacture_report_no": "202206873507"},
    ]
    cl = _group_by_product(ext)
    assert len(cl) == 2


def test_group_floating_label_attaches_by_address():
    """제품명 없는 표시사항이 같은 공장주소의 '라벨 없는' 제품에 붙는다."""
    from chandra.pipeline import _group_by_product

    addr = "충청남도 아산시 음봉면 음봉로 829"
    ext = [
        {"doc_type": DOC_PRODUCT_REPORT, "product_name": "호두아몬드", "manufacture_report_no": "19930461022270", "address": addr},
        {"doc_type": DOC_LABEL, "product_name": "호두아몬드", "address": addr},
        {"doc_type": DOC_PRODUCT_REPORT, "product_name": "검은콩", "manufacture_report_no": "19930461022269", "address": addr},
        {"doc_type": DOC_LABEL, "product_name": None, "address": addr},  # 깨진 라벨
    ]
    cl = _group_by_product(ext)
    assert len(cl) == 2
    # 깨진 라벨은 라벨 없던 '검은콩'에 흡수 → (제품 미상) 클러스터 없음
    assert all(c["name"] != "(제품 미상)" for c in cl)
    geomeun = next(c for c in cl if "검은콩" in (c["key"] or ""))
    assert any(d["doc_type"] == DOC_LABEL for d in geomeun["docs"])


# ---------------------------------------------------------------------------
# 식품유형 합의 (_resolve_food_type)
# ---------------------------------------------------------------------------
def test_resolve_food_type_prefers_report_over_label(monkeypatch):
    import chandra.foodsafety as fs
    from chandra import pipeline

    monkeypatch.setattr(fs, "search_food_spec", lambda *a, **k: [])  # 네트워크 차단
    by_type = {
        DOC_PRODUCT_REPORT: {"food_type": "가공두유"},
        DOC_LABEL: {"food_type": "가공유"},  # 라벨 OCR 오인식
    }
    r = pipeline._resolve_food_type(by_type)
    assert r["value"] == "가공두유"
    assert r["source"] == DOC_PRODUCT_REPORT
    assert r["mismatch"] is True


def test_resolve_food_type_no_mismatch(monkeypatch):
    import chandra.foodsafety as fs
    from chandra import pipeline

    monkeypatch.setattr(fs, "search_food_spec", lambda *a, **k: [{"product_type": "떡류"}])
    by_type = {DOC_PRODUCT_REPORT: {"food_type": "떡류"}, DOC_SELF_QUALITY: {"food_type": "떡류"}}
    r = pipeline._resolve_food_type(by_type)
    assert r["value"] == "떡류" and r["mismatch"] is False and r["registered"] is True


# ---------------------------------------------------------------------------
# 기본정보 출처 우선순위 (_basic_info)
# ---------------------------------------------------------------------------
def test_basic_info_source_priority(monkeypatch):
    import chandra.foodsafety as fs
    from chandra import pipeline

    monkeypatch.setattr(fs, "search_food_spec", lambda *a, **k: [])
    by_type = {
        DOC_PRODUCT_REPORT: {"product_name": "보고서명", "business_name": "제조사", "license_no": "12345678901"},
        DOC_LABEL: {"product_name": "라벨명"},
    }
    rows = {r["field"]: r for r in pipeline._basic_info(by_type)}
    assert rows["제품명"]["value"] == "보고서명"
    assert rows["제품명"]["source"] == DOC_PRODUCT_REPORT
    assert rows["영업등록번호"]["value"] == "12345678901"


# ---------------------------------------------------------------------------
# 자가품질 검사주기 (별표12)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ft,months", [("떡류", 3), ("가공두유", 2), ("양념육", 1), ("탁주", 6), ("조미건어포", 3)])
def test_test_cycle_months(ft, months):
    from chandra.self_quality import test_cycle_months

    assert test_cycle_months(ft) == months


def test_validity_uses_food_type_cycle(monkeypatch):
    """유효기간은 식품유형 검사주기(min 6개월)로 산정 — 비:너지(기타식물성유지=1개월)."""
    import chandra.foodsafety as fs
    from datetime import date
    from chandra.self_quality import build_self_quality_evidence, QualityCertificate

    monkeypatch.setattr(fs, "search_food_spec", lambda *a, **k: [])
    cert = QualityCertificate(food_type="기타식물성유지", issue_date="2025-11-14")
    ev = build_self_quality_evidence(cert, None, None, today=date(2026, 6, 5))
    assert ev["유효기간"]["valid_months"] == 1
    assert ev["유효기간"]["valid"] is False  # 1개월 주기면 2026-06-05엔 만료


def test_self_tested_when_agency_is_manufacturer(monkeypatch):
    """검사기관=제조사 본인이면 영업자 직접 자가품질검사로 인정."""
    import chandra.foodsafety as fs
    from datetime import date
    from chandra.self_quality import build_self_quality_evidence, QualityCertificate

    monkeypatch.setattr(fs, "search_food_spec", lambda *a, **k: [])
    cert = QualityCertificate(
        food_type="기타식물성유지", issue_date="2026-05-20",
        test_agency="주식회사 노바렉스 2공장", manufacturer="주식회사 노바렉스 2공장",
    )
    ev = build_self_quality_evidence(cert, None, None, today=date(2026, 6, 5))
    assert ev["검사기관_제조사동일_자체검사"] is True


# ---------------------------------------------------------------------------
# 소재지 매칭 (시·도 약칭↔정식명)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("q,addr,ok", [
    ("경상북도", "경상북도 칠곡군 지천면", True),
    ("경북", "경상북도 칠곡군", True),
    ("전북특별자치도", "전라북도 전주시", True),
    ("서울특별시", "경기도 성남시", False),
    ("신동로7길", "경상북도 칠곡군 지천면 신동로7길 92", True),
])
def test_address_matches(q, addr, ok):
    from chandra.foodsafety import _address_matches

    assert _address_matches(q, addr) is ok


# ---------------------------------------------------------------------------
# 식품유형 합의 — 보고서 미등록 표기 vs 2개 서류 합의
# ---------------------------------------------------------------------------
def test_food_type_consensus_override(monkeypatch):
    """보고서='육식간조리세트'(미등록) vs 성적서·표시사항='양념육' → 합의값 채택."""
    import chandra.foodsafety as fs
    from chandra import pipeline

    monkeypatch.setattr(fs, "search_food_spec", lambda *a, **k: [])  # 둘 다 미등록
    by_type = {
        DOC_PRODUCT_REPORT: {"food_type": "육식간조리세트"},
        DOC_SELF_QUALITY: {"food_type": "양념육"},
        DOC_LABEL: {"food_type": "양념육"},
    }
    r = pipeline._resolve_food_type(by_type)
    assert r["value"] == "양념육"
    assert r["consensus_override"] is True


# ---------------------------------------------------------------------------
# 고시 첨부 파서 유틸 (law_attachment)
# ---------------------------------------------------------------------------
def test_clean_part_name():
    from chandra.law_attachment import _clean_part_name

    assert _clean_part_name("(1) 제1~제5_개정.hwpx") == "(1) 제1~제5"
    assert _clean_part_name("dir/건강기능식품의 기준 및 규격_(제1~제3).hwpx") == "제1~제3"


def test_part_order():
    from chandra.law_attachment import _part_order

    assert _part_order("(1) 제1.hwpx") == (1, 0)
    assert _part_order("(3-2) 제8.4.hwp") == (3, 2)
    assert _part_order("이름없음.hwp") == (999, 0)


def test_demote_headings():
    from chandra.law_attachment import _demote_headings

    assert _demote_headings("# 제목\n본문\n## 소제목") == "## 제목\n본문\n### 소제목"


def test_is_hwpx_package_and_strip_images():
    from chandra.law_attachment import _is_hwpx_package, _strip_hwpx_images

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/section0.xml", "<x/>")
        z.writestr("BinData/image1.bmp", b"\x00" * 100)
    data = buf.getvalue()
    assert _is_hwpx_package(data) is True
    slim = _strip_hwpx_images(data)
    names = zipfile.ZipFile(io.BytesIO(slim)).namelist()
    assert "BinData/image1.bmp" not in names and "Contents/section0.xml" in names


# ---------------------------------------------------------------------------
# 잡 영속화 (SQLite) — 재시작에도 결과 유지
# ---------------------------------------------------------------------------
def test_jobs_persistence(monkeypatch, tmp_path):
    from chandra_api import jobs

    monkeypatch.setattr(jobs, "_WORK_ROOT", tmp_path)
    monkeypatch.setattr(jobs, "_DB_PATH", tmp_path / "jobs.db")

    jid = jobs.create_job("a.zip", "u1")
    jobs._set(jid, status="running", started=jobs._now())
    jobs._set(jid, status="done", finished=jobs._now(),
              result={"units": [{"products": [{"overall": "적합"}, {"overall": "부적합"}]}]})

    j = jobs.get_job(jid)
    assert j["status"] == "done"
    assert len(j["result"]["units"]) == 1

    lst = jobs.list_jobs("u1")
    assert len(lst) == 1
    assert lst[0]["overall"] == "부적합"  # units 전체 최악
    assert "result" not in lst[0]  # 목록에는 결과 본문 제외
