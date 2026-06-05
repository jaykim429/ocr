import { useState } from "react";
import * as api from "../api";
import { PageHeader, Field } from "../ui";

// 대표 업종 — 식약처 인허가 업종명(자주 쓰는 것 위주, 직접 입력도 가능)
const INDUSTRIES = [
  "식품제조가공업", "식품소분업", "즉석판매제조가공업", "식품첨가물제조업",
  "용기·포장지제조업", "식품운반업", "식품판매업", "식품냉동냉장업",
  "제과점영업", "일반음식점영업", "휴게음식점영업", "집단급식소",
];
// 시·도 (DB 소재지 정식명과 일치하도록 풀네임으로 전송)
const REGIONS = [
  "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시",
  "대전광역시", "울산광역시", "세종특별자치시", "경기도", "강원특별자치도",
  "충청북도", "충청남도", "전북특별자치도", "전라남도", "경상북도",
  "경상남도", "제주특별자치도",
];

export default function BusinessTab() {
  const [q, setQ] = useState("");
  const [lic, setLic] = useState("");
  const [ind, setInd] = useState("");
  const [region, setRegion] = useState("");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<number | null>(null);

  const search = async () => {
    if (!q.trim() && !lic.trim() && !ind && !region) {
      setErr("업소명·영업등록번호·업종·소재지 중 하나 이상 입력하세요");
      return;
    }
    setLoading(true); setErr(""); setOpen(null);
    try {
      setData(await api.searchBusiness({ q: q.trim(), license_no: lic.trim(), industry: ind, address: region }));
    } catch (e: any) { setErr(e.message); }
    finally { setLoading(false); }
  };

  const reset = () => { setQ(""); setLic(""); setInd(""); setRegion(""); setData(null); setErr(""); setOpen(null); };

  const rows: any[] = data?.items || [];
  const inputCls = "w-full rounded-lg border border-slate-300 px-3 py-2 text-base outline-none focus:border-brand-600";

  return (
    <div>
      <PageHeader
        title="식약처 인허가 업체 목록"
        subtitle="식품안전나라 인허가 업소 정보(I2500) · 업소명·영업등록번호·업종·소재지로 상세 검색"
        right="홈 › 인허가 업체 목록"
      />

      {/* 상세 검색 폼 */}
      <form onSubmit={(e) => { e.preventDefault(); search(); }} className="mb-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-600">업소명</span>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="예: 알찬푸드" className={inputCls} />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-600">영업등록번호</span>
            <input value={lic} onChange={(e) => setLic(e.target.value)} placeholder="예: 20200529264" className={inputCls} />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-600">업종</span>
            <select value={ind} onChange={(e) => setInd(e.target.value)} className={inputCls}>
              <option value="">전체</option>
              {INDUSTRIES.map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-600">소재지(시·도)</span>
            <select value={region} onChange={(e) => setRegion(e.target.value)} className={inputCls}>
              <option value="">전체</option>
              {REGIONS.map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          </label>
        </div>
        <div className="mt-4 flex items-center gap-2">
          {err && <p className="text-sm text-rose-600">{err}</p>}
          <button type="button" onClick={reset} className="ml-auto rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50">초기화</button>
          <button className="rounded-lg bg-brand-600 px-6 py-2 text-sm font-semibold text-white hover:bg-brand-700">검색</button>
        </div>
      </form>

      {data && <div className="mb-2 text-base text-slate-500">검색결과 <b className="text-slate-800">{data.count}</b>건</div>}

      {loading ? (
        <div className="rounded-xl border border-slate-200 bg-white p-10 text-center text-slate-400 shadow-sm">검색 중…</div>
      ) : data ? (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-left text-base">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">업종</th>
                <th className="px-4 py-3">업소명</th>
                <th className="px-4 py-3">대표자</th>
                <th className="px-4 py-3">영업등록번호</th>
                <th className="px-4 py-3">소재지</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.length === 0 ? (
                <tr><td colSpan={5} className="px-4 py-10 text-center text-slate-400">결과 없음</td></tr>
              ) : rows.map((r: any, i: number) => (
                <FragmentRow key={i} r={r} open={open === i} onToggle={() => setOpen(open === i ? null : i)} />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-slate-200 bg-white p-10 text-center text-base text-slate-400">
          업소명·영업등록번호·업종·소재지 중 하나 이상으로 검색하세요
        </div>
      )}
    </div>
  );
}

function FragmentRow({ r, open, onToggle }: { r: any; open: boolean; onToggle: () => void }) {
  return (
    <>
      <tr className={`cursor-pointer ${open ? "bg-brand-50" : "hover:bg-slate-50"}`} onClick={onToggle}>
        <td className="px-4 py-3"><span className="rounded bg-slate-100 px-1.5 py-0.5 text-sm text-slate-600">{r.industry}</span></td>
        <td className="px-4 py-3 font-medium text-slate-800"><span className="mr-1 text-slate-400">{open ? "▾" : "▸"}</span>{r.business_name}</td>
        <td className="px-4 py-3 text-slate-600">{r.representative}</td>
        <td className="px-4 py-3 text-slate-500">{r.license_no}</td>
        <td className="px-4 py-3 text-sm text-slate-500">{r.address}</td>
      </tr>
      {open && (
        <tr className="bg-brand-50/40"><td colSpan={5} className="px-6 py-4">
          <div className="rounded-lg border border-brand-100 bg-white p-4">
            <Field label="업소명" value={r.business_name} />
            <Field label="업종" value={r.industry} />
            <Field label="대표자" value={r.representative} />
            <Field label="영업등록번호" value={r.license_no} />
            <Field label="허가일" value={r.permit_date} />
            <Field label="소재지" value={r.address} />
            <Field label="전화" value={r.tel} />
          </div>
        </td></tr>
      )}
    </>
  );
}
