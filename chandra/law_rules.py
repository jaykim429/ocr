"""감시목록 법령·고시 → 표시사항 분석 자동연결(프롬프트 그라운딩).

label_check 의 Gemma 판정에, 제품 속성(원재료·포장재·인증마크·식품유형)에 '해당하는'
고시 표시의무 요지만 골라 '적용 법령 근거'로 주입한다. 판정은 Gemma 가 수행한다
(자가 규칙엔진 아님). 과다알람 방지를 위해 트리거가 있을 때만 주입하고, 문구는
'시안 단계 누락 가능 → 확인필요(부적합 단정 금지)' 기조를 유지한다.

각 규칙의 출처(고시명)는 chandra/data/law_watchlist.json 감시목록에 등재돼 있어,
법제처에서 현행/개정이 추적되고 탭에서 본문·별표를 열람할 수 있다(law_attachment).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# 유전자변형 표시대상 다빈도 승인작물(원재료명에 등장하면 GMO 표시대상 여부 점검)
_GMO_CROPS = (
    "대두", "콩", "옥수수", "옥배유", "콘", "면실", "면화", "목화",
    "카놀라", "유채", "채종유", "사탕무", "알팔파",
)
_GMO_MARKS = ("유전자변형", "비유전자변형", "구분유통", "non-gmo", "gmo", "non gmo")
_PACKAGING = (
    "포장", "재질", "팩", "병", "캔", "봉", "필름", "비닐", "분리배출",
    "pet", "pe", "pp", "ps", "유리", "종이", "알미늄", "알루미늄",
)


@dataclass(frozen=True)
class LawRule:
    name: str          # 고시/법령명 (watchlist 등재명과 일치)
    trigger: Callable[[str, str], bool]  # (food_type, label_text) -> 적용 여부
    snippet: str       # 주입할 표시의무 요지 + 점검 포인트
    basis: str = ""    # 법적 근거(짧은 인용) — 항목별 근거 표시·칩 표출용


RULES: list[LawRule] = [
    LawRule(
        name="유전자변형식품등의 표시기준",
        basis="「유전자변형식품등의 표시기준」제3·5조",
        trigger=lambda ft, t: any(c in t for c in _GMO_CROPS),
        snippet=(
            "「유전자변형식품등의 표시기준」제3·5조: 안전성심사 승인 GMO 농축수산물"
            "(대두·옥수수·면화·카놀라·사탕무·알팔파 등)과 이를 원료로 제조·가공 후에도 "
            "유전자변형 DNA/단백질이 남아 있는 식품은 원재료명 옆 등에 '유전자변형 ○○'를 "
            "표시할 의무가 있다. 단 ①비의도적 혼입 3%이하+구분유통증명서 구비, ②고도정제로 "
            "DNA/단백질이 검출되지 않는 정제당류·정제유지류는 표시가 면제된다. "
            "'Non-GMO·비유전자변형'은 비의도적 혼입치가 0일 때만 표시할 수 있다. "
            "점검: 위 작물이 원재료에 있는데 GMO 관련 표기(유전자변형/구분유통/Non-GMO)가 "
            "전혀 없으면 'GMO 표시대상 여부 확인필요'로 보고(정제유·정제당 면제 가능성 있어 "
            "부적합 단정 금지)."
        ),
    ),
    LawRule(
        name="분리배출 표시에 관한 지침",
        basis="「자원의 절약과 재활용촉진에 관한 법률」§14 · 「분리배출 표시에 관한 지침」",
        trigger=lambda ft, t: any(k in t for k in _PACKAGING),
        snippet=(
            "「분리배출 표시에 관한 지침」: 종이팩·유리·금속캔·합성수지(PET/PE/PP 등)·"
            "복합재질 포장재는 재질 분류명과 분리배출 도안을 표시해야 한다(멸균팩은 "
            "'일반팩/멸균팩' 구분 표기). 표면적 50㎠(필름·시트류 100㎠) 미만 등은 면제. "
            "점검: 포장재 분리배출 표시가 보이지 않으면 '분리배출 표시 확인필요'. 단 인쇄 전 "
            "시안에서는 누락될 수 있으므로 부적합으로 단정하지 말고 확인필요로 안내."
        ),
    ),
    LawRule(
        name="식품 및 축산물 안전관리인증기준",
        basis="「식품 및 축산물 안전관리인증기준(HACCP)」",
        trigger=lambda ft, t: any(k in t.lower() for k in ("haccp", "안전관리인증", "위해요소")),
        snippet=(
            "「식품 및 축산물 안전관리인증기준(HACCP)」: HACCP(안전관리인증) 마크·문구는 "
            "해당 품목·업소가 실제 인증받은 경우에만 표시할 수 있다. 점검: 라벨에 HACCP "
            "마크/문구가 있으면 'HACCP 인증서·인증범위(해당 품목 포함 여부) 확인필요'로 보고"
            "(시스템이 인증 진위를 자동확인하지 못함)."
        ),
    ),
    LawRule(
        name="부당한 표시·광고행위의 유형 및 기준 지정고시",
        basis="「부당한 표시·광고행위의 유형 및 기준 지정고시」",
        trigger=lambda ft, t: True,  # 금지표현 점검 — 위반이 있을 때만 Gemma 가 플래그(저노이즈)
        snippet=(
            "「부당한 표시·광고행위의 유형 및 기준 지정고시」: 질병의 예방·치료 효능을 표방하거나 "
            "의약품으로 오인·혼동시키는 표현, 사실과 다르거나 과장된 표현, 다른 제품 비방, "
            "소비자 기만 표현은 금지된다. 점검: 라벨에 그러한 표현이 있으면 '부당표시 소지 — "
            "확인필요'로 보고(명백하면 부적합)."
        ),
    ),
    LawRule(
        name="건강기능식품의 표시기준",
        basis="「건강기능식품의 표시기준」",
        trigger=lambda ft, t: "건강기능식품" in (ft or ""),
        snippet=(
            "「건강기능식품의 표시기준」: 기능정보, 섭취량·섭취방법·섭취 시 주의사항, "
            "'질병의 예방·치료를 위한 의약품이 아니라는 내용의 표현'을 반드시 표시해야 한다. "
            "점검: 건강기능식품인데 위 항목이 누락되면 '검토필요'."
        ),
    ),
]


def applicable_rules(food_type: str | None, label_text: str) -> list[dict]:
    """제품 속성에 해당하는 고시 근거 목록 [{name, snippet}] 을 반환한다."""
    ft = food_type or ""
    t = label_text or ""
    out = []
    for r in RULES:
        try:
            # 트리거는 소문자 비교가 필요한 규칙(HACCP)을 위해 원문/소문자 모두 접근 가능하도록
            # label_text 원문을 넘기고 규칙 내부에서 .lower() 를 쓴다.
            hit = r.trigger(ft, t)
        except Exception:  # noqa: BLE001 - 트리거 오류는 미적용으로 처리
            hit = False
        if hit:
            out.append({"name": r.name, "snippet": r.snippet, "basis": r.basis})
    return out


def rules_to_block(rules: list[dict]) -> str:
    """이미 선별된 규칙 목록을 프롬프트 주입용 텍스트 블록으로(없으면 빈 문자열).

    호출부가 applicable_rules 를 이미 호출했다면 그 결과를 그대로 넘겨 중복 평가를 피한다.
    """
    if not rules:
        return ""
    lines = [
        "\n\n[적용 법령·고시 근거 — 아래 기준으로 추가 점검하고, 해당 항목을 items 에 포함하세요. "
        "이 근거로 새로 추가하는 items 의 reason 에는 해당 법령·고시명을 함께 적으세요"
        "(예: \"「유전자변형식품등의 표시기준」에 따라 …\").]"
    ]
    for r in rules:
        lines.append(f"· {r['snippet']}")
    return "\n".join(lines)


def grounding_block(food_type: str | None, label_text: str) -> str:
    """적용 고시 근거를 label_check Gemma 프롬프트에 주입할 텍스트 블록(없으면 빈 문자열)."""
    return rules_to_block(applicable_rules(food_type, label_text))
