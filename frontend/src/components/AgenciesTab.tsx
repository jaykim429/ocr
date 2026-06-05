import { useEffect, useState } from "react";
import * as api from "../api";
import { PageHeader, Field } from "../ui";

const CATS = ["", "식품", "축산물", "위생용품"];

// 가나다 정렬 키: (주)/(사)/(유)/(재)/㈜/주식회사/사단법인/재단법인 등 법인표기 제거
function sortKey(name?: string): string {
  return (name || "")
    .replace(/\(주\)|\(유\)|\(사\)|\(재\)|㈜|주식회사|유한회사|사단법인|재단법인|\(사단법인\)|\(재단법인\)/g, "")
    .replace(/\s/g, "")
    .trim();
}

export default function AgenciesTab() {
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [data, setData] = useState<any>({ count: 0, items: [] });
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    const d = await api.listAgencies(q, cat);
    d.items = [...(d.items || [])].sort((a: any, b: any) => sortKey(a.name).localeCompare(sortKey(b.name), "ko"));
    setData(d);
    setLoading(false);
  };
  useEffect(() => { load(); }, [cat]);

  return (
    <div>
      <PageHeader
        title="검사기관 목록"
        subtitle={`식약처 공인 시험·검사기관 현황(2026-04-24) · 총 ${data.count}곳 · 가나다순 · 기관명 클릭 시 상세 펼침`}
        right="홈 › 검사기관 목록"
      />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <form onSubmit={(e) => { e.preventDefault(); load(); }} className="flex gap-2">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="기관명·지정번호·전화·주소 검색"
            className="w-80 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand-600"
          />
          <button className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700">검색</button>
        </form>
        <div className="ml-auto flex gap-1.5">
          {CATS.map((c) => (
            <button
              key={c || "all"}
              onClick={() => setCat(c)}
              className={`rounded-full px-3 py-1.5 text-sm font-medium ring-1 ring-inset ${
                cat === c ? "bg-slate-900 text-white ring-slate-900" : "bg-white text-slate-600 ring-slate-300 hover:bg-slate-50"
              }`}
            >
              {c || "전체"}
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3">분야</th>
              <th className="px-4 py-3">지정번호</th>
              <th className="px-4 py-3">기관명</th>
              <th className="px-4 py-3">전화</th>
              <th className="px-4 py-3">소재지</th>
              <th className="px-4 py-3">유효기간</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-400">불러오는 중…</td></tr>
            ) : data.items.length === 0 ? (
              <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-400">결과 없음</td></tr>
            ) : (
              data.items.map((a: any, i: number) => {
                const key = `${a.category}:${a.designation_no}:${i}`;
                const isOpen = open === key;
                return (
                  <FragmentRow key={key} a={a} isOpen={isOpen} onToggle={() => setOpen(isOpen ? null : key)} />
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function FragmentRow({ a, isOpen, onToggle }: { a: any; isOpen: boolean; onToggle: () => void }) {
  return (
    <>
      <tr className={`cursor-pointer ${isOpen ? "bg-brand-50" : "hover:bg-slate-50"}`} onClick={onToggle}>
        <td className="px-4 py-3"><span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">{a.category}</span></td>
        <td className="px-4 py-3 text-slate-500">{a.designation_no}</td>
        <td className="whitespace-nowrap px-4 py-3 font-medium text-slate-800">
          <span className="mr-1 text-slate-400">{isOpen ? "▾" : "▸"}</span>{a.name}
        </td>
        <td className="px-4 py-3 text-slate-600">{a.tel}</td>
        <td className="px-4 py-3 text-xs text-slate-500">{a.address}</td>
        <td className="px-4 py-3 text-slate-600">{a.valid_until}</td>
      </tr>
      {isOpen && (
        <tr className="bg-brand-50/40">
          <td colSpan={6} className="px-6 py-4">
            <div className="rounded-lg border border-brand-100 bg-white p-4">
              <Field label="기관명" value={a.name} />
              <Field label="분야" value={a.category} />
              <Field label="지정번호" value={a.designation_no} />
              <Field label="대표자" value={a.representative} />
              <Field label="소재지" value={a.address} />
              <Field label="전화" value={a.tel} />
              <Field label="업무범위" value={a.work_scope} />
              <Field label="분야상세" value={a.field_detail} />
              <Field label="시험검사항목" value={(a.scopes || []).join(", ")} />
              <Field label="유효기간" value={a.valid_until} />
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
