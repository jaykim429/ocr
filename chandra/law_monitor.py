"""식약처 식품 관련 법령·행정규칙 모니터링.

감시목록(chandra/data/law_watchlist.json)의 각 법령/행정규칙에 대해 법제처 OPEN API로
현행 상태(공포일·시행일·일련번호·개정구분)를 주기적으로 조회해 스냅샷으로 저장하고,
이전 스냅샷과 비교해 '무엇이 바뀌었는지'를 기록한다.

  - 현행: 시행일 <= 오늘
  - 시행예정: 시행일 > 오늘  (개정안이 공포됐으나 아직 시행 전)
  - 변경점: 일련번호/공포일/시행일/개정구분 변동 → 변경 이벤트로 history 누적
            (조문 단위 신구 대조는 법제처 신구법/3단비교 API로 확장 가능)

라이브 조회는 법제처 OC/서버IP 등록이 필요(chandra.law.LawAuthError). 등록 전에도
감시목록·스냅샷저장·변경감지(diff) 로직은 동작·테스트된다.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

_DATA = Path(__file__).with_name("data")
_WATCHLIST_PATH = _DATA / "law_watchlist.json"
_DB_PATH = _DATA / "law_monitor.json"


def load_watchlist(path: str | Path = _WATCHLIST_PATH) -> list[dict[str, str]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get("watchlist", [])


def make_snapshot(name: str, kind: str) -> dict[str, Any]:
    """법제처 API로 현행/시행예정 상태 스냅샷 생성. 미등록/실패 시 error 필드."""
    from chandra import law

    nm = name.replace(" ", "")
    try:
        if kind == "admrul":
            rules = law.search_admrul(name, rows=10)
            hit = (
                next((r for r in rules if (r.name or "").replace(" ", "") == nm), None)
                or next((r for r in rules if nm in (r.name or "").replace(" ", "")), None)
                or (rules[0] if rules else None)
            )
            if not hit:
                return {"name": name, "kind": kind, "error": "검색결과 없음"}
            return {"name": name, "kind": kind, "rule_name": hit.name, "seq": hit.seq, "status": "현행", "error": None}

        items = law.search_law(name, target="eflaw", rows=20)
        exact = [i for i in items if (i.name or "").replace(" ", "") == nm]
        pool = exact or items
        if not pool:
            return {"name": name, "kind": kind, "error": "검색결과 없음"}
        current = next((i for i in pool if i.history_code == "현행"), None)
        upcoming = [i for i in pool if i.history_code == "시행예정"]
        base = current or pool[0]
        status = "현행" if current else ("시행예정" if upcoming else (base.history_code or "미상"))
        up = sorted(upcoming, key=lambda i: i.enforce_date or "")[0] if upcoming else None
        return {
            "name": name, "kind": kind, "law_name": base.name, "seq": base.seq,
            "promulgation_date": base.promulgation_date, "enforce_date": base.enforce_date,
            "revision_type": base.revision_type, "history_code": base.history_code,
            "status": status,
            "upcoming_enforce_date": up.enforce_date if up else None,
            "upcoming_seq": up.seq if up else None,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - 인증/네트워크 실패
        return {"name": name, "kind": kind, "error": str(exc)}


_TRACKED = ("seq", "promulgation_date", "enforce_date", "revision_type", "status", "upcoming_enforce_date")


def diff_snapshots(old: dict[str, Any] | None, new: dict[str, Any]) -> list[str]:
    """이전/현재 스냅샷 비교 → 변경된 항목을 사람이 읽는 문자열 목록으로."""
    if old is None:
        return ["신규 추적 시작"]
    changes = []
    labels = {
        "seq": "법령일련번호", "promulgation_date": "공포일", "enforce_date": "시행일",
        "revision_type": "제개정구분", "status": "상태", "upcoming_enforce_date": "시행예정일",
    }
    for f in _TRACKED:
        if old.get(f) != new.get(f) and (old.get(f) or new.get(f)):
            changes.append(f"{labels[f]}: {old.get(f)} → {new.get(f)}")
    return changes


def _load_db() -> dict[str, Any]:
    if _DB_PATH.exists():
        return json.loads(_DB_PATH.read_text(encoding="utf-8"))
    return {"items": {}}


def check_updates(today: date | None = None, save: bool = True, prewarm_changed: bool = True) -> dict[str, Any]:
    """감시목록 전체를 조회해 변경을 감지·기록한다.

    반환: {"changed": [...], "upcoming": [...], "errors": [...], "checked": n, "reparsed": [...]}
    prewarm_changed=True 면, 변경된 행정규칙의 고시전문 첨부를 즉시 재변환·캐시한다(개정 시 자동 재적재).
    """
    ref = today or date.today()
    db = _load_db()
    items = db.setdefault("items", {})
    changed, upcoming, errors = [], [], []
    changed_admrul: list[dict[str, Any]] = []

    for w in load_watchlist():
        key = f"{w['kind']}:{w['name']}"
        snap = make_snapshot(w["name"], w["kind"])
        if snap.get("error"):
            errors.append({"item": w["name"], "error": snap["error"]})
            continue
        rec = items.setdefault(key, {"current": None, "history": []})
        ch = diff_snapshots(rec["current"], snap)
        if ch:
            rec["history"].append({"at": ref.isoformat(), "changes": ch, "snapshot": snap})
            rec["current"] = snap
            changed.append({"item": w["name"], "changes": ch})
            if w["kind"] == "admrul":
                changed_admrul.append(snap)
        up_date = snap.get("upcoming_enforce_date") or (
            snap.get("enforce_date") if snap.get("status") == "시행예정" else None
        )
        if up_date:
            upcoming.append({"item": w["name"], "enforce_date": up_date})

    if save:
        _DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")

    # 개정된 행정규칙의 고시전문을 즉시 재변환(새 flSeq 기준 캐시) → 열람 시 즉시 표출
    reparsed: list[dict[str, Any]] = []
    if prewarm_changed and changed_admrul:
        from chandra import law
        from chandra.law_attachment import attachment_markdown

        for snap in changed_admrul:
            try:
                body = law.get_law_body(snap["seq"], target="admrul")
                atts = body.get("attachments") or []
                if atts:
                    r = attachment_markdown(atts[0]["link"])  # 새 flSeq면 새로 변환, 아니면 캐시
                    reparsed.append({"item": snap["name"], "ok": bool(r.get("markdown"))})
            except Exception as exc:  # noqa: BLE001
                reparsed.append({"item": snap["name"], "ok": False, "error": str(exc)[:60]})

    return {"changed": changed, "upcoming": upcoming, "errors": errors,
            "checked": len(load_watchlist()), "reparsed": reparsed}
