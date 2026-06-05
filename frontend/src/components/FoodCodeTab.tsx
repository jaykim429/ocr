import { useEffect, useMemo, useState } from "react";
import * as api from "../api";
import { PageHeader } from "../ui";

// 식품공전 등 식약처 고시(행정규칙) — 법제처 API 본문/별표를 키워드 검색
const CODES = ["식품의 기준 및 규격", "식품등의 표시기준", "식품첨가물의 기준 및 규격", "건강기능식품의 기준 및 규격"];

export default function FoodCodeTab() {
  const [laws, setLaws] = useState<any[]>([]);
  const [pick, setPick] = useState<string>(CODES[0]);
  const [body, setBody] = useState<any>(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState("");

  useEffect(() => { api.getLaws().then((d) => setLaws(d.items || [])); }, []);

  useEffect(() => {
    const law = laws.find((l) => l.name === pick && l.seq);
    if (!law) { setBody(null); return; }
    setLoading(true); setErr(""); setBody(null);
    api.getLawBody(law.seq, "admrul").then(setBody).catch((e) => setErr(e.message)).finally(() => setLoading(false));
  }, [pick, laws]);

  const matches = useMemo(() => {
    if (!body) return [];
    if (!q.trim()) return body.articles;
    const nq = q.replace(/\s/g, "");
    return body.articles.filter((a: any) => (a.content || "").replace(/\s/g, "").includes(nq) || (a.title || "").replace(/\s/g, "").includes(nq));
  }, [body, q]);

  return (
    <div>
      <PageHeader title="식품공전 검색" subtitle="식약처 고시(식품의 기준 및 규격 등) 본문·별표를 검색 · 출처: 법제처 국가법령정보" right="홈 › 식품공전" />

      <div className="mb-3 flex flex-wrap gap-1.5">
        {CODES.map((c) => (
          <button key={c} onClick={() => setPick(c)} className={`rounded-full px-3 py-1.5 text-sm font-medium ring-1 ring-inset ${pick === c ? "bg-slate-900 text-white ring-slate-900" : "bg-white text-slate-600 ring-slate-300 hover:bg-slate-50"}`}>{c}</button>
        ))}
      </div>

      <div className="mb-4 flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 shadow-sm">
        <span className="text-slate-400">🔍</span>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="조문 내용 검색 (예: 세균수, 대장균, 기타수산물가공품, 보존료)" className="w-full text-sm outline-none" />
      </div>

      {err && <p className="text-sm text-rose-600">본문 조회 실패: {err} (법제처 OC/IP 등록 필요할 수 있음)</p>}
      {loading && <p className="text-sm text-slate-400">본문 불러오는 중…</p>}

      {body && (
        <div className="space-y-4">
          <div className="text-sm text-slate-500">조문 {matches.length}{q ? ` / ${body.articles.length}` : ""}건 · 별표 {body.tables.length}건</div>

          {body.tables.length > 0 && (
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="mb-2 text-sm font-semibold text-slate-700">별표·서식 (첨부파일)</div>
              <ul className="space-y-1.5">
                {body.tables.map((t: any, i: number) => (
                  <li key={i} className="flex items-center justify-between rounded border border-slate-100 px-3 py-2 text-sm">
                    <span className="text-slate-700">{t.no ? `[별표 ${t.no}] ` : ""}{t.title || "별표"}</span>
                    <span className="flex gap-2 text-xs">
                      {t.hwp && <a href={t.hwp} target="_blank" rel="noreferrer" className="rounded bg-slate-900 px-2.5 py-1 text-white hover:bg-slate-700">📄 HWP</a>}
                      {t.pdf && <a href={t.pdf} target="_blank" rel="noreferrer" className="rounded bg-rose-600 px-2.5 py-1 text-white hover:bg-rose-500">📕 PDF</a>}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="max-h-[60vh] space-y-4 overflow-auto pr-1">
              {matches.map((a: any, i: number) => (
                <div key={i}>
                  {a.title && <h3 className="mb-1 font-semibold text-brand-700">{a.title}</h3>}
                  <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">{a.content}</p>
                </div>
              ))}
              {matches.length === 0 && <p className="text-sm text-slate-400">검색 결과 없음</p>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
