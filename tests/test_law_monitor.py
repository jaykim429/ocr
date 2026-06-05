from chandra.law_monitor import diff_snapshots, load_watchlist


def test_diff_new_tracking():
    assert diff_snapshots(None, {"seq": "1"}) == ["신규 추적 시작"]


def test_diff_detects_enforce_and_seq_change():
    old = {"seq": "100", "enforce_date": "20250101", "status": "현행", "revision_type": "일부개정"}
    new = {"seq": "101", "enforce_date": "20260701", "status": "시행예정", "revision_type": "일부개정"}
    ch = diff_snapshots(old, new)
    assert any("법령일련번호" in c for c in ch)
    assert any("시행일" in c for c in ch)
    assert any("상태" in c for c in ch)
    assert not any("제개정구분" in c for c in ch)  # 동일 → 변경목록에 없음


def test_diff_no_change():
    snap = {"seq": "1", "enforce_date": "20250101", "status": "현행"}
    assert diff_snapshots(snap, dict(snap)) == []


def test_watchlist_has_food_laws():
    names = [w["name"] for w in load_watchlist()]
    assert "식품위생법" in names
    assert "식품의 기준 및 규격" in names  # 식품공전
    assert "식품등의 표시기준" in names
