import zipfile
from pathlib import Path

from chandra.extraction import DOC_LABEL, DOC_PRODUCT_REPORT, DOC_SELF_QUALITY
from chandra.pipeline import (
    _gather_files,
    _group_by_product,
    _nutrition_map,
    _to_certificate,
    _to_manufacture,
    collect_flags,
)


def test_license_no_derived_from_report_no():
    ext = {
        "doc_type": DOC_PRODUCT_REPORT,
        "product_name": "국내산 꼬마 박대",
        "manufacture_report_no": "2020052926415",
        "business_name": "유한회사 알찬푸드",
        "license_no": None,
    }
    mfr = _to_manufacture(ext)
    # 영업등록번호 = 품목제조보고번호 앞 11자리
    assert mfr.license_no == "20200529264"


def test_to_certificate_parses_items():
    ext = {
        "test_items": [
            {"name": "세균수", "criteria": "n=5, c=2, m=1000000, M=5000000", "results": "340, 180, 260, 310, 490", "judgement": "적합"},
        ],
        "issue_date": "2026-02-20",
        "test_agency": "주식회사 디아이분석센터",
    }
    cert = _to_certificate(ext)
    assert cert.items[0].results == [340, 180, 260, 310, 490]
    assert cert.issue_date == "2026-02-20"


def test_nutrition_map_extracts_numbers():
    ext = {"nutrition": {"나트륨": "550mg", "단백질": "21g", "당류": None}}
    m = _nutrition_map(ext)
    assert m["나트륨"] == 550
    assert m["단백질"] == 21
    assert "당류" not in m


def test_group_by_product_splits_multiproduct():
    ext = [
        {"doc_type": DOC_PRODUCT_REPORT, "product_name": "워커힐 스파이시 폭립"},
        {"doc_type": DOC_SELF_QUALITY, "product_name": "워커힐 스파이시 폭립"},
        {"doc_type": DOC_PRODUCT_REPORT, "product_name": "워커힐 오리지널 폭립"},
        {"doc_type": DOC_SELF_QUALITY, "product_name": "워커힐 오리지널 폭립"},
        {"doc_type": "기타", "product_name": None},  # 무관 문서는 제외
    ]
    clusters = _group_by_product(ext)
    assert len(clusters) == 2
    assert {len(c["docs"]) for c in clusters} == {2}


def test_group_by_product_single():
    ext = [
        {"doc_type": DOC_PRODUCT_REPORT, "product_name": "인생 촉촉 노가리"},
        {"doc_type": DOC_SELF_QUALITY, "product_name": "인생촉촉노가리"},  # 띄어쓰기 차이
        {"doc_type": DOC_LABEL, "product_name": None},  # 이름 없어도 단일제품에 합쳐짐
    ]
    clusters = _group_by_product(ext)
    assert len(clusters) == 1
    assert len(clusters[0]["docs"]) == 3


def test_collect_flags_extracts_issues():
    steps = {
        "step1_license": {"verdict": {"overall_verdict": "부적합", "reasons": ["주소 불일치"]}},
        "step2_nutrition": {"status": "미제출"},
        "step3_self_quality": {"verdict": {"overall_verdict": "적합", "items": []}},
    }
    flags = collect_flags(steps)
    assert len(flags) == 1
    assert flags[0]["step"] == "1. 인허가"
    assert "주소 불일치" in flags[0]["items"]


def test_gather_files_unzips(tmp_path: Path):
    # 더미 zip 생성 후 해제 확인
    src = tmp_path / "a.png"
    src.write_bytes(b"\x89PNG\r\n")
    zpath = tmp_path / "docs.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(src, "a.png")
    files = _gather_files(zpath, tmp_path / "work")
    assert any(f.name == "a.png" for f in files)
