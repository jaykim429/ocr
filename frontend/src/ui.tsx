// 공용 UI 요소 (Linear/Stripe 풍 상태 배지·카드)

const STYLE: Record<string, { dot: string; chip: string; label: string }> = {
  적합: { dot: "bg-emerald-500", chip: "bg-emerald-50 text-emerald-700 ring-emerald-600/20", label: "적합" },
  부적합: { dot: "bg-rose-500", chip: "bg-rose-50 text-rose-700 ring-rose-600/20", label: "부적합" },
  검토필요: { dot: "bg-amber-500", chip: "bg-amber-50 text-amber-800 ring-amber-600/20", label: "검토필요" },
  판정불가: { dot: "bg-slate-400", chip: "bg-slate-100 text-slate-600 ring-slate-500/20", label: "판정불가" },
};

export function VerdictBadge({ value, size = "sm" }: { value?: string; size?: "sm" | "lg" }) {
  const s = STYLE[value || ""] || STYLE["판정불가"];
  const pad = size === "lg" ? "px-3 py-1 text-sm" : "px-2 py-0.5 text-xs";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full font-medium ring-1 ring-inset ${s.chip} ${pad}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {value || "-"}
    </span>
  );
}

// 공용 페이지 헤더 — 세 탭 공통 타이포(제목 text-2xl / 부제 text-sm)
export function PageHeader({ title, subtitle, right }: { title: string; subtitle?: string; right?: React.ReactNode }) {
  return (
    <div className="mb-6 flex items-end justify-between gap-3">
      <div>
        <h2 className="text-2xl font-bold tracking-tight text-slate-900">{title}</h2>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {right && <div className="shrink-0 text-xs text-slate-400">{right}</div>}
    </div>
  );
}

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-slate-200 bg-white shadow-sm ${className}`}>{children}</div>
  );
}

// 현대홈쇼핑 워드마크 (정식 로고는 /logo.png 로 교체 가능)
export function Logo({ className = "" }: { className?: string }) {
  // public/logo.png 가 있으면 그것을, 없으면 컬러블록 워드마크 사용
  return (
    <span className={`inline-flex select-none overflow-hidden rounded text-[13px] font-extrabold leading-none text-white ${className}`}>
      <span className="bg-[#1aa088] px-1.5 py-1">현대홈</span>
      <span className="bg-[#2c2c2c] px-1.5 py-1">쇼</span>
      <span className="bg-[#c8803c] px-1.5 py-1">핑</span>
    </span>
  );
}

export function Dot({ value }: { value?: string }) {
  const s = STYLE[value || ""] || STYLE["판정불가"];
  return <span className={`inline-block h-2 w-2 rounded-full ${s.dot}`} />;
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="max-h-[85vh] w-full max-w-lg overflow-auto rounded-2xl bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
          <h3 className="text-base font-semibold text-slate-900">{title}</h3>
          <button onClick={onClose} className="rounded-lg px-2 py-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700">✕</button>
        </div>
        <div className="px-5 py-4">{children}</div>
      </div>
    </div>
  );
}

export function Field({ label, value }: { label: string; value?: React.ReactNode }) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <div className="flex gap-3 py-1.5 text-sm">
      <span className="w-24 shrink-0 text-slate-400">{label}</span>
      <span className="text-slate-800">{value}</span>
    </div>
  );
}
