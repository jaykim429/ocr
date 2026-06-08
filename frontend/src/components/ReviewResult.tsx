import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { Card, VerdictBadge, Dot } from "../ui";
import * as api from "../api";

const ORDER: Record<string, number> = { 적합: 1, 검토필요: 2, 부적합: 3 };

function worstOf(verdicts: string[]): string {
  let w = "적합";
  for (const v of verdicts) if ((ORDER[v] || 0) > (ORDER[w] || 0)) w = v;
  return verdicts.length ? w : "검토필요";
}

// true/false → 사람이 읽는 한글
function yn(v: any, t = "예", f = "아니오"): string {
  if (v === true) return t;
  if (v === false) return f;
  return "확인 불가";
}

// 정규화(공백 제거) 후 원문에 포함되는지 — 추출값 신뢰도(근거) 점검
function grounded(value: any, ocr?: string): boolean | null {
  if (!value || !ocr) return null;
  const norm = (s: string) => s.replace(/\s|[.,()·ㆍ\-]/g, "");
  const v = norm(String(value));
  if (v.length < 2) return null;
  return norm(ocr).includes(v);
}

// 전체/단위 종합
function unitOverall(unit: any): string {
  return worstOf((unit.products || []).map((p: any) => p.overall));
}

export default function ReviewResult({ report }: { report: any }) {
  // 신·구 리포트 형태 통일: units 없으면 통째로 한 단위로 감싼다
  const units: any[] = report.units || [{ name: null, ...report }];
  const overall = worstOf(units.map(unitOverall));
  const totalProducts = units.reduce((n, u) => n + (u.products?.length || 0), 0);
  const multi = units.length > 1;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xl font-bold text-slate-900">전체 종합</span>
        <VerdictBadge value={overall} size="lg" />
        <span className="text-base text-slate-500">
          검토대상 {units.length}건 · 제품 {totalProducts}건
        </span>
      </div>

      {units.map((u, i) => (
        <UnitView key={i} unit={u} index={i} multi={multi} />
      ))}
    </div>
  );
}

function UnitView({ unit, index, multi }: { unit: any; index: number; multi: boolean }) {
  const [open, setOpen] = useState(index === 0 || !multi);
  const products: any[] = unit.products || [];
  const unexpected: any[] = unit.unexpected_files || [];
  const extractions: any[] = unit.extractions || [];

  if (unit.error) {
    return (
      <div className="rounded-xl border border-rose-200 bg-rose-50 px-5 py-4 text-base text-rose-700">
        <b>{unit.name || "검토대상"}</b> — 검토 중 오류: {unit.error}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {multi && (
        <button
          onClick={() => setOpen(!open)}
          className="flex w-full items-center gap-3 rounded-xl border border-slate-200 bg-white px-5 py-3 text-left shadow-sm hover:bg-slate-50"
        >
          <span className="text-slate-400">{open ? "▾" : "▸"}</span>
          <span className="text-lg font-bold text-slate-900">📁 {unit.name}</span>
          <VerdictBadge value={unitOverall(unit)} />
          <span className="ml-auto text-sm text-slate-400">제품 {products.length}건</span>
        </button>
      )}

      {open && (
        <>
          {unexpected.length > 0 && (
            <div className="rounded-lg bg-amber-50 px-4 py-3 text-base text-amber-900 ring-1 ring-inset ring-amber-600/20">
              ⚠️ 압축파일에 예상 외/미상 파일이 있습니다 (확인 요망, 자동검토 제외)
              <ul className="ml-5 mt-1 list-disc">
                {unexpected.map((u, i) => (
                  <li key={i}>{u.file} <span className="text-amber-700">({u.doc_type}{u.error ? `, 오류:${u.error}` : ""})</span></li>
                ))}
              </ul>
            </div>
          )}
          {products.map((p, i) => (
            <ProductCard key={i} product={p} extractions={extractions} />
          ))}
          {products.length === 0 && (
            <div className="rounded-xl border border-dashed border-slate-200 bg-white p-8 text-center text-base text-slate-400">
              인식된 제품 서류가 없습니다.
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ProductCard({ product, extractions }: { product: any; extractions: any[] }) {
  // 헤더 제품명·식품유형은 기본정보(보고서 우선·합의값)를 신뢰 — OCR 클러스터명/원시추출 대신.
  const binfo: Record<string, string> = Object.fromEntries(
    (product.basic_info || []).map((b: any) => [b.field, b.value]).filter(([, val]: any) => val)
  );
  const productName = binfo["제품명"] || product.product || "(제품명 미상)";
  const foodType =
    binfo["식품유형"] || extractions.map((e) => e.food_type).find(Boolean) || product.food_type || "";
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2 px-6 py-4">
        <div className="flex items-center gap-3">
          <span className="text-lg font-bold text-slate-900">📦 {productName}</span>
          <VerdictBadge value={product.overall} />
        </div>
        <span className="text-sm text-slate-400">{(product.documents_found || []).join(" · ")}</span>
      </div>
      {Array.isArray(product.basic_info) && product.basic_info.some((b: any) => b.value) && (
        <div className="px-6 pb-4">
          <div className="mb-1.5 text-sm font-semibold text-slate-500">기본 정보 (추출 결과 확인)</div>
          <div className="overflow-hidden rounded-lg border border-slate-200">
            <table className="w-full text-left text-[15px]">
              <tbody className="divide-y divide-slate-100">
                {product.basic_info.map((b: any, i: number) => (
                  <tr key={i} className={b.value ? "" : "bg-slate-50/50"}>
                    <td className="w-40 bg-slate-50 px-3 py-2 font-medium text-slate-500">{b.field}</td>
                    <td className="px-3 py-2 text-slate-800">
                      {b.value || <span className="text-amber-600">미추출 — 확인 필요</span>}
                    </td>
                    <td className="w-32 px-3 py-2 text-right text-xs text-slate-400">{b.source || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <FoodTypeWarning check={product.food_type_check} />
      <div className="px-6 pb-4">
        <Highlight flags={product.flags || []} />
      </div>
      <StepPanel title="1단계 · 인허가 적합성" step={product.steps?.step1_license} />
      <StepPanel title="2단계 · 영양성분 비교" step={product.steps?.step2_nutrition} />
      <StepPanel title="3단계 · 자가품질검사" step={product.steps?.step3_self_quality} foodType={foodType} />
      <StepPanel title="4단계 · 표시사항 검토" step={product.steps?.step4_label} />
      <ExtractionPanel extractions={extractions} />
    </Card>
  );
}

// 식품유형 오류 신호: 문서 간 표기 불일치 / 식품공전 미등록 표기
function FoodTypeWarning({ check }: { check: any }) {
  if (!check) return null;
  const msgs: string[] = [];
  if (check.mismatch && Array.isArray(check.candidates)) {
    const list = check.candidates.map((c: any) => `${c.doc}: ${c.food_type}`).join(" / ");
    msgs.push(`문서마다 식품유형 표기가 다릅니다 — ${list} (가장 신뢰도 높은 ‘${check.source}’ 값을 채택)`);
  }
  if (check.registered === false && check.value) {
    msgs.push(`‘${check.value}’ 은 식품공전에 정확히 등록된 표기가 아닙니다 — OCR 오인식 가능, 식품유형 확인 필요`);
  }
  if (!msgs.length) return null;
  return (
    <div className="mx-6 mb-3 rounded-lg bg-amber-50 px-4 py-2.5 text-sm text-amber-900 ring-1 ring-inset ring-amber-600/20">
      <span className="font-semibold">⚠ 식품유형 확인 필요</span>
      <ul className="ml-5 mt-0.5 list-disc">{msgs.map((m, i) => <li key={i}>{m}</li>)}</ul>
    </div>
  );
}

function Highlight({ flags }: { flags: any[] }) {
  if (!flags?.length)
    return (
      <div className="rounded-lg bg-emerald-50 px-4 py-3 text-base font-medium text-emerald-800 ring-1 ring-inset ring-emerald-600/20">
        ✅ 모든 단계 적합 — 별도로 확인할 항목이 없습니다.
      </div>
    );
  const hasFail = flags.some((f) => f.verdict === "부적합");
  return (
    <div className={`rounded-lg px-4 py-3 text-base ring-1 ring-inset ${hasFail ? "bg-rose-50 text-rose-800 ring-rose-600/20" : "bg-amber-50 text-amber-900 ring-amber-600/20"}`}>
      <div className="mb-1.5 font-bold">{hasFail ? "🔴 부적합 / 확인 필요 항목" : "🟡 담당자 확인이 필요한 항목"}</div>
      {flags.map((f, i) => (
        <div key={i} className="mb-1">
          <span className="font-semibold">[{f.step}] {f.verdict}</span>
          <ul className="ml-5 list-disc">
            {f.items.map((it: string, j: number) => <li key={j}>{it}</li>)}
          </ul>
        </div>
      ))}
    </div>
  );
}

function StepPanel({ title, step, foodType }: { title: string; step: any; foodType?: string }) {
  const [specOpen, setSpecOpen] = useState(false);
  const v = step?.verdict;
  const ev = step?.evidence || {};
  return (
    <div className="border-t border-slate-100 px-6 py-4">
      <div className="mb-2 flex items-center justify-between">
        <h4 className="text-base font-bold text-slate-800">{title}</h4>
        <div className="flex items-center gap-2">
          {title.startsWith("3단계") && foodType && (
            <button
              onClick={() => setSpecOpen((o) => !o)}
              className="rounded-lg border border-brand-200 bg-brand-50 px-3 py-1 text-sm font-semibold text-brand-700 hover:bg-brand-100"
            >
              📖 식품공전 규격 {specOpen ? "닫기" : "보기"}
            </button>
          )}
          {step?.status ? <span className="text-sm text-slate-400">{stepStatusKo(step.status)}</span> : <VerdictBadge value={v?.overall_verdict} />}
        </div>
      </div>

      {v && (() => {
        // 단계 내 항목을 '적합' vs '확인 필요'로 분리해서 보여준다.
        const good: { key: string; node: ReactNode }[] = [];
        const check: { key: string; node: ReactNode }[] = [];
        const push = (ok: boolean, key: string, node: ReactNode) =>
          (ok ? good : check).push({ key, node });

        if ("exists_in_db" in v) {
          push(!!v.exists_in_db, "db", <span><b>안전나라 DB 존재</b>: {yn(v.exists_in_db, "있음", "없음")}</span>);
          push(!!v.label_matches_license_doc, "lm", <span><b>표시사항 ↔ 인허가서류 대조</b>: {yn(v.label_matches_license_doc, "일치", "불일치")}</span>);
        }
        (Array.isArray(v.items) ? v.items : []).forEach((it: any, i: number) =>
          push(it.verdict === "적합", `it${i}`, <span><b>{it.name}</b>: {it.reason}</span>));
        if (ev["검사기관_검증"]) {
          const f = ev["검사기관_검증"].found || ev["검사기관_제조사동일_자체검사"];
          push(!!f, "agency",
            <span><b>검사기관</b>: {ev["검사기관_제조사동일_자체검사"]
              ? "영업자 직접 자가품질검사(별표12 제5호) — 적법"
              : `${yn(ev["검사기관_검증"].found, "공인 확인됨", "미확인")} — ${ev["검사기관_검증"].detail}`}</span>);
        }
        if (ev["유효기간"]) push(ev["유효기간"].valid === true, "valid", <span>📅 <b>유효기간</b>: {ev["유효기간"].detail}</span>);
        (Array.isArray(v.comparisons) ? v.comparisons : []).forEach((c: any, i: number) =>
          push(c.verdict === "적합", `c${i}`, <span><b>{c.name}</b>: {c.detail}</span>));

        const Group = ({ label, color, list }: { label: string; color: string; list: typeof good }) =>
          list.length ? (
            <div>
              <div className={`mb-1 text-sm font-bold ${color}`}>{label}</div>
              <ul className="space-y-1 text-[15px] text-slate-700">
                {list.map((x) => <li key={x.key} className="flex gap-2"><Dot value={label.includes("적합") ? "적합" : "검토필요"} /><span>{x.node}</span></li>)}
              </ul>
            </div>
          ) : null;

        return (
          <div className="space-y-2.5">
            <Group label={`⚠️ 확인 필요 (${check.length})`} color="text-amber-700" list={check} />
            <Group label={`✅ 적합 확인 (${good.length})`} color="text-emerald-700" list={good} />
            {(v.reasons || []).length > 0 && (
              <ul className="mt-1 space-y-1 text-[15px] text-slate-500">
                {(v.reasons || []).map((r: string, i: number) => <li key={`r${i}`}>· {r}</li>)}
              </ul>
            )}
          </div>
        );
      })()}
      {step?.["표시기준단위"] && (
        <p className="text-[15px] text-slate-600">📐 표시 기준단위: <b>{step["표시기준단위"]}</b>{step["성적서기준단위"] ? ` · 성적서 기준: ${step["성적서기준단위"]}` : ""}</p>
      )}
      {step?.["단위환산"] && (
        <p className="text-[15px] text-slate-600">🔄 단위 환산: {step["단위환산"]}</p>
      )}
      {step?.["성적서_검증"] && (
        <div className="mt-1.5 rounded-lg bg-slate-50 px-3 py-2 text-[15px] text-slate-700 ring-1 ring-inset ring-slate-200">
          <b>영양성분성적서</b>:
          {" "}검사기관 {step["성적서_검증"]["검사기관_검증"]?.found ? "✅ 공인 확인" : "⚠ 미확인"}
          {step["성적서_검증"]["발급일"] ? ` · 발급일 ${step["성적서_검증"]["발급일"]}` : ""}
          {step["성적서_검증"]["검사목적"] ? ` · 목적 ${step["성적서_검증"]["검사목적"]}` : ""}
          {step["성적서_검증"]["검사목적_참고용"] ? " (⚠ 참고용 — 공식 검증용 아님)" : ""}
        </div>
      )}
      {step?.["표시사항_영양성분"] && (
        <p className="text-[15px] text-slate-500">
          표시사항 영양성분: {Object.entries(step["표시사항_영양성분"]).map(([k, val]) => `${k}=${val}`).join(", ") || "(미추출)"}
        </p>
      )}
      {step?.["식품유형_참고"] && (
        <p className="mt-1.5 rounded-lg bg-sky-50 px-3 py-2 text-[15px] text-sky-900 ring-1 ring-inset ring-sky-600/15">
          💡 <b>식품유형 대비 참고</b>(판정 아님): {step["식품유형_참고"]}
        </p>
      )}

      {specOpen && foodType && <FoodSpecInline foodType={foodType} />}
    </div>
  );
}

function stepStatusKo(s: string): string {
  return ({ pending: "대기", running: "처리 중", skipped: "해당 없음", "미실행": "해당 없음" } as Record<string, string>)[s] || s;
}

// 식품공전(I0930) 규격을 인라인(카드 전체 폭)으로 펼쳐서 쭉 읽기
function FoodSpecInline({ foodType }: { foodType: string }) {
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    setData(null); setErr("");
    api.getFoodSpec(foodType).then(setData).catch((e) => setErr(e.message));
  }, [foodType]);
  return (
    <div className="mt-3 rounded-lg border border-brand-200 bg-brand-50/40 p-4">
      <div className="mb-2 flex items-baseline gap-2">
        <span className="text-base font-bold text-slate-800">📖 식품공전 규격 — {foodType}</span>
        {data && <span className="text-sm text-slate-500">{data.count}개 항목</span>}
      </div>
      <p className="mb-3 text-sm text-slate-500">식품안전나라 식품공전(I0930) 기준규격 · 성적서 결과를 이 규격과 대조하세요.</p>
      {err && <p className="text-sm text-rose-600">조회 실패: {err}</p>}
      {!data && !err && <p className="text-sm text-slate-400">불러오는 중…</p>}
      {data && data.count === 0 && (
        <p className="text-sm text-slate-500">식품공전에 '{foodType}' 품목명으로 등록된 규격이 없습니다. (식품유형 표기를 확인하세요)</p>
      )}
      {data && data.count > 0 && (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-left text-[15px]">
            <thead className="bg-slate-100 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2 w-48">시험항목</th>
                <th className="px-3 py-2 w-48">세부항목</th>
                <th className="px-3 py-2">기준규격</th>
                <th className="px-3 py-2 w-24">단위</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.items.map((r: any, i: number) => (
                <tr key={i} className="hover:bg-slate-50">
                  <td className="px-3 py-2 font-medium text-slate-800">{r.item}</td>
                  <td className="px-3 py-2 text-slate-600">{r.sub_item}</td>
                  <td className="px-3 py-2 text-slate-700">{r.spec}</td>
                  <td className="px-3 py-2 text-slate-500">{r.unit}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// 추출 원문 ↔ 판독값 + 신뢰도(근거) 점검
const KEY_FIELDS: [string, string][] = [
  ["product_name", "제품명"], ["food_type", "식품유형"], ["business_name", "제조사/영업자"],
  ["address", "소재지"], ["license_no", "영업등록번호"], ["manufacture_report_no", "품목보고번호"],
  ["issue_date", "발급일"], ["test_agency", "검사기관"],
];

function ExtractionPanel({ extractions }: { extractions: any[] }) {
  const [open, setOpen] = useState(false);
  if (!extractions?.length) return null;
  return (
    <div className="border-t border-slate-100">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 px-6 py-3 text-left text-base font-semibold text-slate-600 hover:bg-slate-50">
        <span className="text-slate-400">{open ? "▾" : "▸"}</span> 추출 원문 ↔ 판독값 대조 (신뢰도 점검)
      </button>
      {open && (
        <div className="space-y-4 px-6 pb-5">
          {extractions.map((e, i) => <DocExtraction key={i} ext={e} />)}
        </div>
      )}
    </div>
  );
}

function DocExtraction({ ext }: { ext: any }) {
  const ocr: string = ext._ocr_text || "";
  const fields = KEY_FIELDS.filter(([k]) => ext[k]);
  const lowConf = fields.filter(([k]) => grounded(ext[k], ocr) === false);
  return (
    <div className="rounded-lg border border-slate-200">
      <div className="flex items-center gap-2 border-b border-slate-100 bg-slate-50 px-4 py-2">
        <span className="rounded bg-slate-200 px-2 py-0.5 text-sm font-semibold text-slate-700">{ext.doc_type}</span>
        {lowConf.length > 0 && (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-sm font-medium text-amber-800">⚠ 원문 미확인 {lowConf.length}건 — 직접 확인 필요</span>
        )}
      </div>
      <div className="grid gap-4 px-4 py-3 lg:grid-cols-2">
        {/* 판독값 */}
        <div>
          <div className="mb-1.5 text-sm font-semibold text-slate-400">판독값 (AI 추출)</div>
          <table className="w-full text-[15px]">
            <tbody>
              {fields.map(([k, label]) => {
                const g = grounded(ext[k], ocr);
                return (
                  <tr key={k}>
                    <td className="py-1 pr-3 align-top text-slate-400">{label}</td>
                    <td className="py-1 text-slate-800">
                      {String(ext[k])}
                      {g === false && <span className="ml-1.5 rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800">원문 미확인</span>}
                      {g === true && <span className="ml-1.5 text-emerald-600" title="원문에서 확인됨">✓</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {/* 추출 원문 (판독값 하이라이트) */}
        <div>
          <div className="mb-1.5 text-sm font-semibold text-slate-400">추출 원문 (OCR/문서 텍스트)</div>
          <div className="max-h-72 overflow-auto rounded bg-slate-50 p-3 text-sm leading-relaxed text-slate-700">
            <HighlightedText text={ocr} terms={fields.map(([k]) => String(ext[k]))} />
          </div>
        </div>
      </div>
    </div>
  );
}

// 원문 안에서 판독값을 노란색으로 하이라이트
function HighlightedText({ text, terms }: { text: string; terms: string[] }) {
  if (!text) return <span className="text-slate-400">(원문 텍스트 없음)</span>;
  const uniq = Array.from(new Set(terms.filter((t) => t && t.length >= 2)));
  if (!uniq.length) return <span className="whitespace-pre-wrap">{text}</span>;
  const esc = uniq.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).sort((a, b) => b.length - a.length);
  const re = new RegExp(`(${esc.join("|")})`, "g");
  const parts = text.split(re);
  return (
    <span className="whitespace-pre-wrap">
      {parts.map((p, i) =>
        uniq.includes(p) ? <mark key={i} className="rounded bg-amber-200 px-0.5">{p}</mark> : <span key={i}>{p}</span>
      )}
    </span>
  );
}
