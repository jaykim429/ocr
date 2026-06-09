import type { ReactNode } from "react";
import { createContext, Fragment, useContext, useEffect, useState } from "react";
import { Card, VerdictBadge, Dot } from "../ui";
import * as api from "../api";

// 적용 법령 칩 클릭 → 법령 탭에서 해당 고시 열람(앱이 핸들러 주입). 깊은 prop 드릴링 방지용 컨텍스트.
type OpenLaw = (l: { name: string; kind: string }) => void;
const OpenLawCtx = createContext<OpenLaw | null>(null);

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

export default function ReviewResult({ report, onOpenLaw }: { report: any; onOpenLaw?: OpenLaw }) {
  // 신·구 리포트 형태 통일: units 없으면 통째로 한 단위로 감싼다
  const units: any[] = report.units || [{ name: null, ...report }];
  const overall = worstOf(units.map(unitOverall));
  const totalProducts = units.reduce((n, u) => n + (u.products?.length || 0), 0);
  const multi = units.length > 1;

  return (
    <OpenLawCtx.Provider value={onOpenLaw || null}>
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
    </OpenLawCtx.Provider>
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
  // 부적합(차단)과 검토필요(확인)를 색·순서로 분리 — 부적합 사유를 먼저, 명확히.
  const fail = flags.filter((f) => f.verdict === "부적합");
  const check = flags.filter((f) => f.verdict !== "부적합");
  const Group = ({ list, title, cls }: { list: any[]; title: string; cls: string }) =>
    list.length ? (
      <div className={`rounded-lg px-4 py-3 text-[15px] ring-1 ring-inset ${cls}`}>
        <div className="mb-1.5 font-bold">{title}</div>
        <div className="space-y-1.5">
          {list.map((f, i) => (
            <div key={i} className="flex flex-wrap gap-x-2">
              <span className="shrink-0 font-semibold">[{f.step}]</span>
              <span>{f.items.join(" · ")}</span>
            </div>
          ))}
        </div>
      </div>
    ) : null;
  return (
    <div className="space-y-2">
      <Group list={fail} title="🔴 부적합 — 입점 기준 미달(반드시 조치)" cls="bg-rose-50 text-rose-800 ring-rose-600/25" />
      <Group list={check} title="🟡 확인 필요 — 담당자 검토 권장" cls="bg-amber-50 text-amber-900 ring-amber-600/20" />
    </div>
  );
}

// ── 결과 표 (절제·고급: 얇은 라인 / 중립 슬레이트 / 판정 점+좌측 액센트) ──
const THEAD = "bg-slate-50/80 text-[11px] font-semibold uppercase tracking-wider text-slate-400";
const TH = "px-3.5 py-2 font-semibold";
const TD = "px-3.5 py-2.5 align-top";
const NUM = "tabular-nums font-mono text-[13px] text-slate-700";

function vbar(v?: string) {
  return v === "적합" ? "border-transparent" : v === "부적합" ? "border-rose-300" : "border-amber-300";
}
function VerdictCell({ v }: { v?: string }) {
  const c = v === "적합" ? "text-emerald-600" : v === "부적합" ? "text-rose-600" : "text-amber-600";
  if (!v) return <span className="text-slate-300">—</span>;
  return <span className={`inline-flex items-center gap-1.5 whitespace-nowrap text-[13px] font-semibold ${c}`}><Dot value={v} />{v}</span>;
}
function TableWrap({ head, children }: { head: ReactNode; children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200">
      <table className="w-full text-left text-[14px]">
        <thead className={THEAD}>{head}</thead>
        <tbody className="divide-y divide-slate-100">{children}</tbody>
      </table>
    </div>
  );
}
const dash = (x: any) => (x === 0 || x ? x : "—");

// 표에 담기지 않는 단계 신호(유효기간·검사기관)용 절제된 한 줄 정보 박스(심각도별 색)
function InfoLine({ level, icon, label, text }: { level: "ok" | "warn" | "bad"; icon: string; label: string; text: string }) {
  const c = level === "ok" ? "bg-emerald-50/60 text-emerald-900 ring-emerald-600/15"
    : level === "bad" ? "bg-rose-50/70 text-rose-900 ring-rose-600/25"
    : "bg-amber-50/60 text-amber-900 ring-amber-600/15";
  return (
    <div className={`flex gap-2 rounded-lg px-3 py-2 text-[13px] ring-1 ring-inset ${c}`}>
      <span className="shrink-0">{icon}</span>
      <span><b className="font-semibold">{label}</b> · {text}</span>
    </div>
  );
}

// 1단계: 인허가서류 ↔ 표시사항 ↔ 안전나라 DB 3출처 대조표
function LicenseTable({ ev, v }: { ev: any; v: any }) {
  const db = ev["영업등록번호_정확매칭"] || (ev["안전나라_DB_조회결과"] || [])[0] || {};
  const doc = ev["인허가서류"] || {};
  const lab = ev["표시사항"] || {};
  const labV = ev["표시사항_검증"] || {};
  // 상호: 영업등록번호로 DB와 동일 영업자 확정(name_match)이면 DB 정식상호를 확정값으로 표시하고
  // 라벨 OCR 오독(그린피시팜→그린피시잠)은 작은 주석으로 남긴다(투명성 유지, 노이즈 제거).
  const labName = lab["제조사명"] || labV["name_seen"];
  const nameCanon = v?.name_match && db.business_name ? db.business_name : labName;
  const nameNote = v?.name_match && db.business_name && labName && labName !== db.business_name ? `OCR: ${labName}` : null;
  const rows = [
    { f: "상호(영업자명)", d: doc["영업자명"], l: nameCanon, note: nameNote, b: db.business_name, ok: v?.name_match },
    { f: "영업등록번호", d: doc["영업등록번호"], l: null, note: null, b: db.license_no, ok: v?.exists_in_db },
    { f: "소재지", d: doc["주소"], l: lab["소재지"] || labV["address_seen"], note: null, b: db.address, ok: v?.address_match },
    { f: "대표자", d: doc["대표자"], l: null, note: null, b: null, ok: null },
  ];
  return (
    <TableWrap head={<tr><th className={TH}>대조 항목</th><th className={TH}>인허가서류</th><th className={TH}>표시사항</th><th className={TH}>안전나라 DB</th><th className={`${TH} w-24`}>판정</th></tr>}>
      {rows.map((r, i) => (
        <tr key={i} className={`border-l-2 ${r.ok === false ? vbar("검토필요") : "border-transparent"} hover:bg-slate-50/50`}>
          <td className={`${TD} font-medium text-slate-500`}>{r.f}</td>
          <td className={`${TD} text-slate-800`}>{dash(r.d)}</td>
          <td className={`${TD} text-slate-800`}>{dash(r.l)}{r.note && <span className="ml-1 text-[11px] text-slate-400">({r.note})</span>}</td>
          <td className={`${TD} text-slate-800`}>{dash(r.b)}</td>
          <td className={TD}>{r.ok === null ? <span className="text-slate-300">—</span> : <VerdictCell v={r.ok ? "적합" : "검토필요"} />}</td>
        </tr>
      ))}
    </TableWrap>
  );
}

// 2단계: 영양성분 비교표 (표시값 ↔ 성적서 실측 ↔ 비율 ↔ 판정)
function NutritionTable({ comparisons }: { comparisons: any[] }) {
  return (
    <TableWrap head={<tr><th className={TH}>영양성분</th><th className={TH}>표시값</th><th className={TH}>성적서 실측</th><th className={`${TH} w-24`}>측정/표시</th><th className={`${TH} w-24`}>판정</th></tr>}>
      {comparisons.map((c, i) => (
        <Fragment key={i}>
          <tr className={`border-l-2 ${c.verdict === "적합" ? "border-transparent" : vbar(c.verdict)} hover:bg-slate-50/50`}>
            <td className={`${TD} font-medium text-slate-700`}>{c.name}</td>
            <td className={`${TD} ${NUM}`}>{dash(c.label_value)}{c.label_value != null && c.unit ? c.unit : ""}</td>
            <td className={`${TD} ${NUM}`}>{dash(c.measured_value)}{c.measured_value != null && c.unit ? c.unit : ""}</td>
            <td className={`${TD} ${NUM}`}>{c.ratio != null ? `${Math.round(c.ratio * 100)}%` : "—"}</td>
            <td className={TD}><VerdictCell v={c.verdict} /></td>
          </tr>
          {c.detail && c.verdict !== "적합" && <tr className="bg-slate-50/30"><td className="px-3.5 pb-2 pt-0 text-[12px] text-slate-500" colSpan={5}>↳ {c.detail}</td></tr>}
        </Fragment>
      ))}
    </TableWrap>
  );
}

// 3단계: 식품공전 규격 ↔ 성적서 결과 대조표 (근거는 하위 들여쓴 행)
function SelfQualityTable({ ev, v }: { ev: any; v: any }) {
  const items = Array.isArray(v?.items) ? v.items : [];
  if (!items.length) return null;
  const tests = ev["성적서"]?.["시험항목"] || [];
  const specs = ev["식품공전_규격"]?.["규격항목"] || [];
  const norm = (s: any) => String(s || "").replace(/\s/g, "");
  const find = (arr: any[], n: string) => arr.find((x) => norm(x.name) === norm(n)) || {};
  return (
    <TableWrap head={<tr><th className={TH}>시험항목</th><th className={TH}>식품공전 규격</th><th className={TH}>적용조건</th><th className={TH}>성적서 결과</th><th className={`${TH} w-24`}>판정</th></tr>}>
      {items.map((it: any, i: number) => {
        const sp = find(specs, it.name); const ts = find(tests, it.name);
        const result = Array.isArray(ts["결과"]) ? ts["결과"].join(", ") : dash(ts["결과"]);
        return (
          <Fragment key={i}>
            <tr className={`border-l-2 ${vbar(it.verdict)} hover:bg-slate-50/50`}>
              <td className={`${TD} font-medium text-slate-700`}>{it.name}</td>
              <td className={`${TD} text-slate-600`}>{dash(sp["기준"] || ts["성적서_기준"])}</td>
              <td className={`${TD} text-[13px] text-slate-500`}>{dash(sp["적용조건"])}</td>
              <td className={`${TD} ${NUM}`}>{result}</td>
              <td className={TD}><VerdictCell v={it.verdict} /></td>
            </tr>
            {it.reason && <tr className="bg-slate-50/30"><td className="px-3.5 pb-2 pt-0 text-[12px] leading-snug text-slate-500" colSpan={5}>↳ {it.reason}</td></tr>}
          </Fragment>
        );
      })}
    </TableWrap>
  );
}

// 4단계: 의무 표시항목 체크리스트 (항목 ↔ 기재여부 ↔ 근거)
function LabelTable({ v }: { v: any }) {
  const items = Array.isArray(v?.items) ? v.items : [];
  if (!items.length) return null;
  return (
    <TableWrap head={<tr><th className={`${TH} w-64`}>의무 표시항목</th><th className={`${TH} w-24`}>기재여부</th><th className={TH}>근거</th></tr>}>
      {items.map((it: any, i: number) => (
        <tr key={i} className={`border-l-2 ${vbar(it.verdict)} hover:bg-slate-50/50`}>
          <td className={`${TD} font-medium text-slate-700`}>{it.name}</td>
          <td className={TD}><VerdictCell v={it.verdict === "적합" ? "적합" : it.verdict} /></td>
          <td className={`${TD} text-[13px] text-slate-500`}>{it.reason}</td>
        </tr>
      ))}
    </TableWrap>
  );
}

// 단계별 적절한 표를 선택 렌더. 표가 없으면 null(기존 사유 요약만 표시).
function StepTable({ title, step }: { title: string; step: any }) {
  const v = step?.verdict; const ev = step?.evidence || {};
  if (title.startsWith("1") && v && "exists_in_db" in v) return <LicenseTable ev={ev} v={v} />;
  if (title.startsWith("2") && Array.isArray(v?.comparisons) && v.comparisons.length) return <NutritionTable comparisons={v.comparisons} />;
  if (title.startsWith("3")) return <SelfQualityTable ev={ev} v={v} />;
  if (title.startsWith("4")) return <LabelTable v={v} />;
  return null;
}

function StepPanel({ title, step, foodType }: { title: string; step: any; foodType?: string }) {
  const [specOpen, setSpecOpen] = useState(false);
  const openLaw = useContext(OpenLawCtx);
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

      {(v || ev["유효기간"] || ev["검사기관_검증"]) && (
        <div className="space-y-3">
          <StepTable title={title} step={step} />

          {/* 적용 법령·고시 근거 칩 (자동연결된 고시) — 클릭 시 법령 탭에서 본문 열람 */}
          {(ev["적용_법령근거"] || []).length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">적용 법령·고시</span>
              {ev["적용_법령근거"].map((l: any, i: number) => {
                const name = typeof l === "string" ? l : l.name;
                const label = typeof l === "string" ? l : (l.basis || l.name);
                const kind = (typeof l === "string" ? "admrul" : (l.kind || "admrul"));
                return openLaw ? (
                  <button key={i} onClick={() => openLaw({ name, kind })} title={`${name} — 본문 보기`}
                    className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600 ring-1 ring-inset ring-transparent hover:bg-brand-50 hover:text-brand-700 hover:ring-brand-600/20">
                    {label} <span className="text-slate-400">↗</span>
                  </button>
                ) : (
                  <span key={i} className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600" title={name}>{label}</span>
                );
              })}
            </div>
          )}

          {/* 표에 담기지 않는 단계 신호: 유효기간 · 검사기관(3단계) */}
          {(ev["유효기간"] || ev["검사기관_검증"]) && (
            <div className="space-y-1.5">
              {ev["유효기간"] && (
                <InfoLine level={ev["유효기간"].valid === true ? "ok" : "bad"} icon="📅"
                  label="유효기간" text={ev["유효기간"].detail} />
              )}
              {ev["검사기관_검증"] && (
                <InfoLine level={(ev["검사기관_검증"].found || ev["검사기관_제조사동일_자체검사"]) ? "ok" : "warn"} icon="🏛"
                  label="검사기관"
                  text={ev["검사기관_제조사동일_자체검사"]
                    ? "영업자 직접 자가품질검사(별표12 제5호) — 적법"
                    : `${yn(ev["검사기관_검증"].found, "공인 확인됨", "미확인")} — ${ev["검사기관_검증"].detail}`} />
              )}
            </div>
          )}

          {(v?.reasons || []).length > 0 && (
            <details className="text-[13px] text-slate-500">
              <summary className="cursor-pointer select-none text-slate-400 hover:text-slate-600">종합 사유 {v.reasons.length}건 보기</summary>
              <ul className="ml-4 mt-1 space-y-0.5">{v.reasons.map((r: string, i: number) => <li key={i}>· {r}</li>)}</ul>
            </details>
          )}
        </div>
      )}
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
