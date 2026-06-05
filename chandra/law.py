"""법제처 국가법령정보 OPEN API 연계 — 행정규칙 본문 + 별표·서식(HWP/PDF).

워크플로 2·3의 법적기준을 자동 수집한다:
  - 「식품등의 표시기준」(영양성분 허용오차 [별지1])
  - 「식품의 기준 및 규격」(식품공전), 식품유형별 검사항목 별표

별표·서식 파일(HWP/PDF)을 받아 chandra.kordoc 으로 마크다운 변환 → 룰셋에 주입한다.

주의: 법제처 OPEN API 는 OC(사용자ID)에 호출 서버 IP/도메인을 사전 등록해야 한다
(open.law.go.kr). 미등록 시 '사용자 정보 검증에 실패' 응답 → AuthError 로 surface.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chandra.settings import settings


class LawAuthError(RuntimeError):
    """OC/IP 미등록 등 사용자 검증 실패."""


def _get(path: str, params: dict[str, Any], retries: int = 3) -> bytes:
    import time

    params = {"OC": settings.LAW_OC, **params}
    url = f"{settings.LAW_API_BASE.rstrip('/')}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    last: Exception | None = None
    for attempt in range(retries):
        try:
            data = urllib.request.urlopen(req, timeout=settings.LAW_TIMEOUT_SECONDS).read()
        except Exception as exc:  # noqa: BLE001 - 간헐적 연결 리셋 재시도
            last = exc
            time.sleep(1.5 * (attempt + 1))
            continue
        head = data[:400].decode("utf-8", errors="replace")
        if "사용자 정보 검증에 실패" in head or "IP주소" in head:
            raise LawAuthError(
                "법제처 OPEN API 사용자 검증 실패 — open.law.go.kr 에 서버 IP/도메인 등록 필요"
                f" (OC={settings.LAW_OC})"
            )
        return data
    raise RuntimeError(f"법제처 API 호출 실패(재시도 {retries}회): {last}")


@dataclass
class AdmRule:
    name: str
    seq: str | None  # 행정규칙일련번호
    detail_link: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "seq": self.seq, "detail_link": self.detail_link}


def search_admrul(query: str, rows: int = 20) -> list[AdmRule]:
    """행정규칙 목록 조회 (예: '식품등의 표시기준', '식품의 기준 및 규격')."""
    data = _get("DRF/lawSearch.do", {"target": "admrul", "type": "XML", "query": query, "display": rows})
    root = ET.fromstring(data)
    out: list[AdmRule] = []
    for node in root.iter("admrul"):
        def t(tag: str) -> str | None:
            el = node.find(tag)
            return el.text.strip() if el is not None and el.text else None

        out.append(AdmRule(name=t("행정규칙명") or "", seq=t("행정규칙일련번호"), detail_link=t("행정규칙상세링크")))
    return out


@dataclass
class LawItem:
    name: str
    seq: str | None  # 법령일련번호
    promulgation_date: str | None  # 공포일자
    enforce_date: str | None  # 시행일자
    revision_type: str | None  # 제개정구분명
    history_code: str | None  # 현행연혁코드 (현행/시행예정/연혁)
    detail_link: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "seq": self.seq,
            "promulgation_date": self.promulgation_date,
            "enforce_date": self.enforce_date,
            "revision_type": self.revision_type,
            "history_code": self.history_code, "detail_link": self.detail_link,
        }


def search_law(query: str, target: str = "eflaw", rows: int = 20) -> list[LawItem]:
    """현행법령 목록 조회. target=eflaw(시행일 기준)/law(공포일 기준)."""
    data = _get("DRF/lawSearch.do", {"target": target, "type": "XML", "query": query, "display": rows})
    root = ET.fromstring(data)
    out: list[LawItem] = []
    for node in root.iter("law"):
        def t(tag: str) -> str | None:
            el = node.find(tag)
            return el.text.strip() if el is not None and el.text else None

        out.append(LawItem(
            name=t("법령명한글") or "", seq=t("법령일련번호"),
            promulgation_date=t("공포일자"), enforce_date=t("시행일자"),
            revision_type=t("제개정구분명"), history_code=t("현행연혁코드"),
            detail_link=t("법령상세링크"),
        ))
    return out


def get_admrul_xml(seq: str) -> bytes:
    """행정규칙 본문 조회 (별표 링크 포함). seq = 행정규칙일련번호."""
    return _get("DRF/lawService.do", {"target": "admrul", "type": "XML", "ID": seq})


def get_law_body(seq: str, target: str = "eflaw") -> dict[str, Any]:
    """법령/행정규칙 본문을 본문(조문)·부칙·별표(첨부링크)로 구조화한다.

    주의: 법령 본문은 target=law + MST(법령일련번호)로 조회해야 한다.
    target=eflaw + MST 조합은 법제처에서 '일치하는 법령이 없습니다'로 빈 응답을 준다.
    """
    if target == "admrul":
        data = _get("DRF/lawService.do", {"target": "admrul", "type": "XML", "ID": seq})
    else:
        data = _get("DRF/lawService.do", {"target": "law", "type": "XML", "MST": seq})
    root = ET.fromstring(data)
    base = settings.LAW_API_BASE.rstrip("/")

    def txt(el, tag: str) -> str | None:
        e = el.find(tag)
        return e.text.strip() if e is not None and e.text and e.text.strip() else None

    name = None
    for tag in ("법령명_한글", "법령명한글", "행정규칙명"):
        for el in root.iter(tag):
            if el.text and el.text.strip():
                name = el.text.strip()
                break
        if name:
            break

    articles = []
    for a in root.iter("조문단위"):
        yn = txt(a, "조문여부")
        content = txt(a, "조문내용") or ""
        title = txt(a, "조문제목")
        # 장/절/편/관 헤더: 조문여부=전문 + 조문내용이 '제N장/절/편/관 ...'
        if yn == "전문" or (not title and re.match(r"^제\s*\d+\s*[편장절관]", content)):
            m = re.match(r"^제\s*\d+\s*([편장절관])", content)
            level = {"편": 0, "장": 1, "절": 2, "관": 3}.get(m.group(1) if m else "", 1)
            if content:
                articles.append({"type": "head", "level": level, "text": content})
            continue
        # 조: 조문내용(표제+본문) + 항/호/목 조립
        parts = [content]
        for hang in a.findall("항"):
            ht = (hang.findtext("항내용") or "").strip()
            if ht:
                parts.append(ht)
            for ho in hang.findall("호"):
                hot = (ho.findtext("호내용") or "").strip()
                if hot:
                    parts.append("  " + hot)
                for mok in ho.findall("목"):
                    mt = (mok.findtext("목내용") or "").strip()
                    if mt:
                        parts.append("    " + mt)
        full = "\n".join(p for p in parts if p)
        if full:
            articles.append({
                "type": "article", "no": txt(a, "조문번호"),
                "branch": txt(a, "조문가지번호"),  # 제7조'의2' 등 가지번호
                "title": title, "content": full,
            })

    addenda = []
    for b in root.iter("부칙단위"):
        contents = [e.text.strip() for e in b.findall("부칙내용") if e.text and e.text.strip()]
        addenda.append({
            "promul_no": txt(b, "부칙공포번호"), "date": txt(b, "부칙공포일자"),
            "content": "\n".join(contents),
        })

    tables = []
    for t in root.iter("별표단위"):
        hwp = txt(t, "별표서식파일링크")
        pdf = txt(t, "별표서식PDF파일링크")
        tables.append({
            "no": txt(t, "별표번호"),
            "title": txt(t, "별표제목") or txt(t, "별표제목문자열"),
            "hwp": base + hwp if hwp else None,
            "pdf": base + pdf if pdf else None,
        })

    # 고시(행정규칙)는 본문 대신 '고시전문' 첨부파일(ZIP/HWP/PDF)로 제공되는 경우가 많다.
    names = [e.text.strip() for e in root.iter("첨부파일명") if e.text and e.text.strip()]
    links = [e.text.strip() for e in root.iter("첨부파일링크") if e.text and e.text.strip()]
    attachments = [{"name": n, "link": link} for n, link in zip(names, links)]

    # 본문 표출용 첨부 우선순위: 실제 본문(전문 또는 법령명과 일치하는 파일) 먼저,
    # 공고·개정이유·신구조문은 뒤로.
    core = re.sub(r"\s", "", name or "")

    def _att_priority(a: dict[str, Any]) -> int:
        nm = a["name"]
        stem = re.sub(r"\s|\.\w+$", "", nm)  # 공백·확장자 제거
        if "신구" in nm:
            return 6
        if "이유" in nm or "공고" in nm:
            return 5
        if "전문" in nm:
            return 0
        if core and (core in stem or stem in core):  # 법령명과 일치 = 본문
            return 1
        if nm.lower().endswith((".hwp", ".hwpx")):  # 본문은 보통 HWP
            return 2
        return 3

    attachments.sort(key=_att_priority)

    return {"name": name, "articles": articles, "addenda": addenda, "tables": tables, "attachments": attachments}


_ATTACH_TAGS = ("별표서식파일링크", "별표서식PDF파일링크")


def attachment_links(body_xml: bytes) -> list[str]:
    """본문 XML 에서 별표·서식 파일(HWP/PDF) 다운로드 경로를 추출."""
    text = body_xml.decode("utf-8", errors="replace")
    links: list[str] = []
    for tag in _ATTACH_TAGS:
        links += re.findall(rf"<{tag}>\s*(?:<!\[CDATA\[)?\s*(/[^<\]]+?)\s*(?:\]\]>)?\s*</{tag}>", text)
    return [link.strip() for link in links if link.strip()]


def download_attachment(link: str, out_path: str | Path) -> Path:
    """별표 파일 물리 다운로드 (link 예: /LSW/flDownload.do?flSeq=...)."""
    url = settings.LAW_API_BASE.rstrip("/") + link
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = urllib.request.urlopen(req, timeout=settings.LAW_TIMEOUT_SECONDS).read()
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def fetch_admrul_tables_markdown(query: str, out_dir: str | Path) -> dict[str, Any]:
    """행정규칙 검색 → 본문 → 별표(HWP/PDF) 다운로드 → kordoc 마크다운.

    반환: {"rule": 행정규칙명, "tables": [{"file","markdown"}...]}. 법적기준 룰셋 주입용.
    """
    from chandra import kordoc

    rules = search_admrul(query, rows=5)
    if not rules:
        return {"rule": None, "tables": [], "note": f"검색 결과 없음: {query}"}
    rule = rules[0]
    body = get_admrul_xml(rule.seq) if rule.seq else b""
    tables = []
    for i, link in enumerate(attachment_links(body)):
        ext = ".pdf" if "PDF" in link or link.lower().endswith(".pdf") else ".hwp"
        f = download_attachment(link, Path(out_dir) / f"{rule.seq}_{i}{ext}")
        tables.append({"file": str(f), "markdown": kordoc.to_markdown(str(f))})
    return {"rule": rule.name, "seq": rule.seq, "tables": tables}
