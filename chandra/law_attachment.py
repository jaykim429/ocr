"""법제처 고시 '고시전문' 첨부파일(HWPX/HWP/ZIP) → 마크다운.

식품공전(식품의 기준 및 규격)·식품등의 표시기준 같은 고시는 본문 조문(XML)이 비어 있고
실제 내용 전체가 '고시전문' 첨부파일에 들어 있다. 이 첨부파일을 받아 chandra.kordoc 으로
변환해 화면에 본문으로 렌더링한다.

첨부파일 형태:
  - 단일 HWPX/HWP  (예: 표시기준 — ZIP 매직이지만 그 자체가 HWPX 패키지)
  - 여러 문서가 든 ZIP (예: 식품공전 — 제1~제9장·별표가 .hwpx/.hwp 로 분리, 일부는 중첩 ZIP)

변환 결과는 data/law_attachments/{flseq}.md 로 캐시한다(첫 변환만 느리고 이후 즉시).
"""

from __future__ import annotations

import io
import re
import urllib.request
import zipfile
from pathlib import Path

from chandra import kordoc
from chandra.settings import settings

_CACHE = Path(__file__).with_name("data") / "law_attachments"
_DOC_EXTS = (".hwp", ".hwpx", ".hwpml", ".docx", ".doc")


def _clean_part_name(name: str) -> str:
    """ZIP 내부 파일명을 읽기 좋은 섹션 제목으로.

    - '(1) 제1~제5_개정.hwpx' → '(1) 제1~제5'  (앞의 (N) 번호 유지)
    - '…/건강기능식품의 기준 및 규격_(제1~제3).hwpx' → '제1~제3'  (뒤 괄호 부분만)
    """
    base = Path(name).name
    base = re.sub(r"\.(hwpx?|docx?|pdf)$", "", base, flags=re.I)
    base = re.sub(r"_?개정$", "", base)
    # 앞에 (N)/(N-M) 번호가 있으면 그대로 유지
    if re.match(r"^\(\d", base):
        return base.replace("_", " ").strip()
    # 뒤쪽 괄호 부분(제1~제3 등)이 있으면 그것만 사용
    m = re.search(r"\(([^)]+)\)\s*$", base)
    if m:
        return m.group(1).strip()
    return base.replace("_", " ").strip() or name


def _part_order(name: str) -> tuple[int, int]:
    """파일명 앞의 '(N)' 또는 '(N-M)' 으로 정렬 키 생성: (1)<(2)<...<(3-1)<(3-2)<...<(9)."""
    m = re.match(r"\((\d+)(?:-(\d+))?\)", Path(name).name)
    return (int(m.group(1)), int(m.group(2) or 0)) if m else (999, 0)


def _demote_headings(md: str) -> str:
    """파트 본문 내부의 기존 #~##### 제목을 한 단계 강등한다.

    kordoc 이 문서 내부 제목을 #(h1)로 출력하는 경우가 있어, 파트 목차(네비)에 섞인다.
    파트 제목만 h1 으로 두기 위해 본문 제목은 ## 이상으로 낮춘다(최대 h6).
    """
    return re.sub(
        r"(?m)^(#{1,6})(\s)",
        lambda m: "#" * min(6, len(m.group(1)) + 1) + m.group(2),
        md,
    )


def _flseq(link: str) -> str | None:
    m = re.search(r"flSeq=(\d+)", link)
    return m.group(1) if m else None


def _download(link: str, retries: int = 3) -> bytes:
    import time

    url = link if link.startswith("http") else settings.LAW_API_BASE.rstrip("/") + link
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    last: Exception | None = None
    for attempt in range(retries):
        try:
            return urllib.request.urlopen(req, timeout=max(settings.LAW_TIMEOUT_SECONDS, 180)).read()
        except Exception as exc:  # noqa: BLE001 - 대용량 첨부 다운로드 중 간헐적 연결 리셋 재시도
            last = exc
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"첨부 다운로드 실패(재시도 {retries}회): {last}")


def _is_hwpx_package(data: bytes) -> bool:
    """ZIP 매직이지만 내부에 mimetype/Contents/section*.xml 가 있으면 HWPX 패키지 자체."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return False
    names = z.namelist()
    return "mimetype" in names or any(n.startswith("Contents/section") for n in names)


def _convert_bytes(data: bytes, suffix: str, work: Path) -> str | None:
    f = work / f"doc{suffix}"
    f.write_bytes(data)
    return kordoc.to_markdown(str(f), timeout=300)


def _strip_hwpx_images(data: bytes) -> bytes | None:
    """HWPX(zip)에서 BinData(이미지)를 제거해 재압축한다.

    이미지가 많은 대형 HWPX 는 kordoc 의 'ZIP bomb' 가드(압축해제 크기 초과)에 걸린다.
    텍스트·표는 Contents/section*.xml 에 있으므로 이미지를 빼면 변환이 통과한다.
    """
    try:
        zin = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in zin.namelist():
            if n.startswith("BinData/"):
                continue
            zout.writestr(n, zin.read(n))
    return buf.getvalue()


def _hwpx_to_md(data: bytes, work: Path) -> str | None:
    """HWPX 변환: 그대로 시도 → 실패 시 이미지 제거 후 재시도(대형 공전 대응)."""
    md = _convert_bytes(data, ".hwpx", work)
    if md:
        return md
    slim = _strip_hwpx_images(data)
    if slim and len(slim) != len(data):
        return _convert_bytes(slim, ".hwpx", work)
    return None


def _parse_zip(data: bytes, work: Path, depth: int = 0) -> list[tuple[str, str]]:
    """ZIP 내부의 문서들을 각각 변환. 중첩 ZIP 은 한 단계 재귀. [(파일명, 마크다운)...]."""
    z = zipfile.ZipFile(io.BytesIO(data))
    out: list[tuple[str, str]] = []
    for info in z.infolist():
        if info.is_dir():
            continue
        # ZIP 내부 파일명은 보통 CP949. 깨져도 변환에는 영향 없음(표시용으로만 복원 시도).
        raw = info.filename
        try:
            name = raw.encode("cp437").decode("cp949")
        except Exception:  # noqa: BLE001
            name = raw
        ext = Path(name).suffix.lower()
        content = z.read(info)
        if ext in _DOC_EXTS:
            md = _hwpx_to_md(content, work) if ext == ".hwpx" else _convert_bytes(content, ext, work)
            if md:
                out.append((name, md))
        elif ext == ".zip" and depth < 1:
            out.extend(_parse_zip(content, work, depth + 1))
    return out


def attachment_markdown(link: str, *, refresh: bool = False) -> dict[str, object]:
    """고시전문 첨부파일을 마크다운으로 변환(캐시).

    반환: {"flseq", "markdown", "parts": [{"name"}...], "cached"}.
    kordoc 미설치/변환 실패 시 markdown=None.
    """
    flseq = _flseq(link) or "unknown"
    _CACHE.mkdir(parents=True, exist_ok=True)
    cache_file = _CACHE / f"{flseq}.md"
    if cache_file.exists() and not refresh:
        return {"flseq": flseq, "markdown": cache_file.read_text(encoding="utf-8"), "parts": [], "cached": True}

    if not kordoc.available():
        return {"flseq": flseq, "markdown": None, "parts": [], "cached": False, "error": "kordoc 미설치"}

    data = _download(link)
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        if data[:4] == b"PK\x03\x04":
            # ZIP 매직: HWPX 패키지 자체이거나, 여러 문서가 든 ZIP(식품공전 등)
            if _is_hwpx_package(data):
                md = _hwpx_to_md(data, work)
                parts, markdown = [{"name": "고시전문"}], (md or "")
            else:
                docs = _parse_zip(data, work)
                docs.sort(key=lambda d: _part_order(d[0]))  # (1)→(9), (3-1)→(3-7) 순
                parts = [{"name": _clean_part_name(n)} for n, _ in docs]
                # 파트 제목만 h1, 본문 내부 제목은 강등 → 네비가 (1)~(9) 파트만 깔끔히 표시
                markdown = "\n\n".join(f"# {_clean_part_name(n)}\n\n{_demote_headings(md)}" for n, md in docs)
        elif data[:8] == bytes.fromhex("d0cf11e0a1b11ae1"):
            # OLE2 복합문서 = 바이너리 HWP(또는 구 워드) — .hwp 로 저장해 변환
            md = _convert_bytes(data, ".hwp", work)
            parts, markdown = [{"name": "고시전문"}], (md or "")
        elif data[:4] == b"%PDF":
            md = _convert_bytes(data, ".pdf", work)  # 텍스트레이어 PDF 만 변환됨
            parts, markdown = [{"name": "고시전문"}], (md or "")
        else:
            # 미상 형식: HWP 로 시도
            md = _convert_bytes(data, ".hwp", work)
            parts, markdown = [{"name": "고시전문"}], (md or "")

    if markdown:
        cache_file.write_text(markdown, encoding="utf-8")
    return {"flseq": flseq, "markdown": markdown or None, "parts": parts, "cached": False}


def _primary_attachment_link(seq: str, target: str = "admrul") -> str | None:
    """행정규칙/법령 본문에서 표출용 1순위 첨부('전문' 등) 링크를 얻는다."""
    from chandra import law

    body = law.get_law_body(seq, target=target)
    atts = body.get("attachments") or []
    return atts[0]["link"] if atts else None


def prewarm(kinds: tuple[str, ...] = ("admrul",)) -> dict[str, object]:
    """감시목록의 고시(행정규칙) 본문 첨부를 미리 변환·캐시한다(적재/갱신 시 1회).

    캐시는 flSeq 기준이라, 고시가 개정되면(첨부 flSeq 변경) 다음 prewarm 에서 자동 재변환된다.
    이미 캐시된 것은 건너뛴다. 열람 시 즉시 응답하도록 사전 적재하는 용도.
    반환: {"warmed": [...], "skipped": [...], "errors": [...]}.
    """
    import json

    from chandra.law_monitor import _DB_PATH, load_watchlist

    db = json.loads(_DB_PATH.read_text(encoding="utf-8")).get("items", {}) if _DB_PATH.exists() else {}
    warmed, skipped, errors = [], [], []
    for w in load_watchlist():
        if w["kind"] not in kinds:
            continue
        cur = (db.get(f"{w['kind']}:{w['name']}") or {}).get("current") or {}
        seq = cur.get("seq")
        if not seq:
            errors.append({"item": w["name"], "error": "seq 없음(모니터 갱신 필요)"})
            continue
        try:
            link = _primary_attachment_link(seq, target=w["kind"])
            if not link:
                skipped.append({"item": w["name"], "reason": "첨부 없음(조문 본문)"})
                continue
            flseq = _flseq(link) or "unknown"
            if (_CACHE / f"{flseq}.md").exists():
                skipped.append({"item": w["name"], "reason": "이미 캐시됨", "flseq": flseq})
                continue
            r = attachment_markdown(link)
            (warmed if r.get("markdown") else errors).append(
                {"item": w["name"], "flseq": flseq, "len": len(r.get("markdown") or "")}
            )
        except Exception as exc:  # noqa: BLE001
            errors.append({"item": w["name"], "error": str(exc)[:80]})
    return {"warmed": warmed, "skipped": skipped, "errors": errors}
