"""검토 잡 관리 — 업로드된 서류를 백그라운드 스레드로 run_quality_review 실행.

검토는 수 분 걸리므로 비동기 잡 + 폴링. 잡 상태·결과를 SQLite 에 영속화하여
서버를 재시작해도 진행/완료 잡과 결과 리포트가 유지된다.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_WORK_ROOT = Path(__file__).resolve().parent.parent / "data" / "reviews"
_DB_PATH = _WORK_ROOT / "jobs.db"
_LOCK = threading.Lock()  # SQLite 쓰기 직렬화(짧은 트랜잭션)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def work_dir(job_id: str) -> Path:
    return _WORK_ROOT / job_id


def _conn() -> sqlite3.Connection:
    _WORK_ROOT.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, status TEXT, owner TEXT, input_name TEXT,
            created TEXT, started TEXT, finished TEXT, error TEXT, result_json TEXT
        )"""
    )
    # 진행 단계 표시용 컬럼(기존 DB 호환 위해 ALTER 로 추가)
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN progress TEXT")
    except sqlite3.OperationalError:
        pass  # 이미 존재
    return conn


def create_job(input_name: str, owner: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _LOCK, _conn() as conn:
        conn.execute(
            "INSERT INTO jobs(id,status,owner,input_name,created) VALUES(?,?,?,?,?)",
            (job_id, "pending", owner, input_name, _now()),
        )
    return job_id


_COLS = {"status", "started", "finished", "error", "progress"}


def set_progress(job_id: str, text: str) -> None:
    """현재 진행 단계 안내문을 갱신(폴링으로 노출)."""
    _set(job_id, progress=text)


def _set(job_id: str, **kw: Any) -> None:
    cols, vals = [], []
    for k, v in kw.items():
        if k == "result":
            cols.append("result_json = ?")
            vals.append(json.dumps(v, ensure_ascii=False) if v is not None else None)
        elif k in _COLS:
            cols.append(f"{k} = ?")
            vals.append(v)
    if not cols:
        return
    vals.append(job_id)
    with _LOCK, _conn() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(cols)} WHERE id = ?", vals)


def _row_to_job(row: sqlite3.Row, with_result: bool = True) -> dict[str, Any]:
    keys = row.keys()
    job = {
        "id": row["id"], "status": row["status"], "owner": row["owner"],
        "input_name": row["input_name"], "created": row["created"],
        "started": row["started"], "finished": row["finished"], "error": row["error"],
        "progress": row["progress"] if "progress" in keys else None,
    }
    if with_result:
        job["result"] = json.loads(row["result_json"]) if row["result_json"] else None
    return job


def get_job(job_id: str) -> dict[str, Any] | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row) if row else None


def list_jobs(owner: str | None = None) -> list[dict[str, Any]]:
    with _conn() as conn:
        if owner:
            rows = conn.execute("SELECT * FROM jobs WHERE owner = ? ORDER BY created DESC", (owner,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM jobs ORDER BY created DESC").fetchall()
    out = []
    for row in rows:
        job = _row_to_job(row, with_result=False)
        report = json.loads(row["result_json"]) if row["result_json"] else None
        job["overall"] = _overall(report)
        out.append(job)
    return out


def _overall(report: dict[str, Any] | None) -> str | None:
    """리포트(단일 또는 units) 전체의 최악 판정."""
    if not report:
        return None
    order = {"적합": 1, "검토필요": 2, "부적합": 3}
    units = report.get("units") or [report]
    worst = None
    for u in units:
        for p in u.get("products", []):
            v = p.get("overall")
            if worst is None or order.get(v, 0) > order.get(worst, 0):
                worst = v
    return worst


def run_job(job_id: str, inputs: list[Path], out_dir: Path, today: date | None = None) -> None:
    """백그라운드 실행 본체. inputs = 검토대상 목록(zip/폴더). 여러 개면 병렬 판정."""
    from chandra.pipeline import run_quality_review_batch

    _set(job_id, status="running", started=_now(), progress="제출 서류 판독 준비 중…")
    try:
        report = run_quality_review_batch(
            inputs, out_dir, today=today,
            on_progress=lambda text: set_progress(job_id, text),
        )
        _set(job_id, status="done", result=report, finished=_now(), progress="검토 완료")
    except Exception as exc:  # noqa: BLE001
        _set(job_id, status="error", error=str(exc), finished=_now())


def start_job(job_id: str, inputs: list[Path], out_dir: Path, today: date | None = None) -> None:
    threading.Thread(
        target=run_job, args=(job_id, inputs, out_dir, today), daemon=True
    ).start()
