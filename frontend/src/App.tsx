import { Component, useEffect, useState } from "react";
import type { ReactNode } from "react";
import * as api from "./api";
import ReviewResult from "./components/ReviewResult";
import AgenciesTab from "./components/AgenciesTab";
import LawsTab from "./components/LawsTab";
import BusinessTab from "./components/BusinessTab";
import { Logo, PageHeader } from "./ui";

const APP_TITLE = "AI 기반 사전 QA 자동화 시스템";
const APP_SUBTITLE = "식품분야";

// 한 화면의 렌더 오류가 앱 전체를 화이트스크린으로 날리지 않도록 보호
class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidUpdate(prev: { children: ReactNode }) {
    if (prev.children !== this.props.children && this.state.error) this.setState({ error: null });
  }
  render() {
    if (this.state.error)
      return (
        <div className="m-2 rounded-xl border border-rose-200 bg-rose-50 p-6 text-sm text-rose-700">
          <div className="mb-2 text-base font-bold">화면을 표시하는 중 오류가 발생했습니다</div>
          <pre className="whitespace-pre-wrap text-xs text-rose-600">{String(this.state.error?.message || this.state.error)}</pre>
          <button onClick={() => this.setState({ error: null })} className="mt-3 rounded-lg bg-rose-600 px-4 py-2 font-semibold text-white hover:bg-rose-500">다시 시도</button>
        </div>
      );
    return this.props.children;
  }
}

export default function App() {
  const [authed, setAuthed] = useState(!!api.getToken());
  if (!authed) return <Login onDone={() => setAuthed(true)} />;
  return <Shell onLogout={() => { api.clearToken(); setAuthed(false); }} />;
}

function Login({ onDone }: { onDone: () => void }) {
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try { await api.login(u, p); onDone(); }
    catch (e: any) { setErr(e.message); }
    finally { setBusy(false); }
  };
  return (
    <div className="flex min-h-full items-center justify-center bg-gradient-to-br from-slate-100 to-slate-200 p-6">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-7 shadow-lg">
        <div className="mb-6">
          <Logo className="mb-3 text-base" />
          <h1 className="text-xl font-bold text-slate-900">{APP_TITLE}</h1>
          <p className="mt-0.5 text-sm font-medium text-[#1aa088]">{APP_SUBTITLE}</p>
        </div>
        <input className="mb-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="아이디" value={u} onChange={(e) => setU(e.target.value)} />
        <input className="mb-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" placeholder="비밀번호" type="password" value={p} onChange={(e) => setP(e.target.value)} />
        {err && <p className="mb-3 text-sm text-rose-600">{err}</p>}
        <button disabled={busy} className="w-full rounded-lg bg-slate-900 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50">
          {busy ? "확인 중…" : "로그인"}
        </button>
      </form>
    </div>
  );
}

const TABS = [
  { id: "review", label: "품질검토", icon: "🧪" },
  { id: "business", label: "업체 검색", icon: "🔎" },
  { id: "agencies", label: "검사기관 목록", icon: "🏢" },
  { id: "laws", label: "법령·규제", icon: "📜" },
];

function Shell({ onLogout }: { onLogout: () => void }) {
  const [tab, setTab] = useState("review");
  const [agencies, setAgencies] = useState<any>(null);
  const [job, setJob] = useState<any>(null);
  useEffect(() => { api.getAgencies().then(setAgencies); }, []);

  // 검토 잡 폴링은 Shell(항상 마운트)에서 — 탭을 이동했다 와도 계속 진행/갱신됨
  useEffect(() => {
    if (!job?.id || job.status === "done" || job.status === "error") return;
    const t = setInterval(async () => {
      try { setJob(await api.getReview(job.id)); }
      catch (e: any) { if (e.message === "unauthorized") onLogout(); }
    }, 3000);
    return () => clearInterval(t);
  }, [job?.id, job?.status]);

  return (
    <div className="flex h-screen">
      {/* 좌측 네비 */}
      <aside className="flex w-72 shrink-0 flex-col overflow-y-auto border-r border-slate-200 bg-white">
        <div className="px-6 py-5">
          <Logo className="text-sm" />
          <div className="mt-3 text-base font-bold leading-snug text-slate-900">{APP_TITLE}</div>
          <div className="text-sm font-semibold text-[#1aa088]">{APP_SUBTITLE}</div>
        </div>
        <nav className="flex-1 px-4 py-2">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`mb-1.5 flex w-full items-center gap-3 rounded-xl px-4 py-3 text-[16px] font-semibold ${
                tab === t.id ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
              }`}
            >
              <span className="text-xl">{t.icon}</span> {t.label}
            </button>
          ))}
        </nav>
        <div className="border-t border-slate-100 px-6 py-4 text-sm text-slate-400">
          {agencies && <div className="mb-1.5">공인 검사기관 {agencies.count}곳</div>}
          <button onClick={onLogout} className="text-slate-500 hover:text-slate-700">로그아웃</button>
        </div>
      </aside>

      {/* 본문 */}
      <main className="flex-1 overflow-auto">
        <div className="px-10 py-8">
          <ErrorBoundary>
            {tab === "review" && <ReviewTab job={job} setJob={setJob} onLogout={onLogout} />}
            {tab === "business" && <BusinessTab />}
            {tab === "agencies" && <AgenciesTab />}
            {tab === "laws" && <LawsTab />}
          </ErrorBoundary>
        </div>
      </main>
    </div>
  );
}

// 진행 단계(경과시간 기반 안내 — 실제 단계와 근사)
const STAGES = [
  "파일 판독·OCR 중",
  "제조사 인허가 조회 중",
  "영양성분 대조 중",
  "자가품질 성적서 ↔ 식품공전 규격 비교 중",
  "검사기관 공인 확인·종합 판정 중",
];

function ReviewProgress({ job }: { job: any }) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (job.status === "done" || job.status === "error") return;
    const t = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [job.status]);
  // 경과 초: started(없으면 created) 기준
  const start = job.started || job.created;
  const elapsed = start ? Math.max(0, (Date.now() - new Date(start).getTime()) / 1000) : tick;
  // 예상 소요 ~120초로 92%까지 점근, 완료 시 100%
  const pct = job.status === "done" ? 100 : Math.min(92, Math.round((1 - Math.exp(-elapsed / 60)) * 100));
  const stage = STAGES[Math.min(STAGES.length - 1, Math.floor(elapsed / 24))];
  return (
    <div>
      <div className="mb-2 flex items-center justify-between text-sm">
        <span className="inline-flex items-center gap-2 font-medium text-slate-700">
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600" />
          {stage}
        </span>
        <span className="tabular-nums text-slate-500">{pct}% · {Math.round(elapsed)}초 경과</span>
      </div>
      <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
        <div className="h-full rounded-full bg-brand-600 transition-all duration-700" style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-2 text-xs text-slate-400">다른 탭으로 이동해도 검토는 계속 진행됩니다.</p>
    </div>
  );
}

function ReviewTab({ job, setJob, onLogout }: { job: any; setJob: (j: any) => void; onLogout: () => void }) {
  const [files, setFiles] = useState<File[]>([]);
  const [today, setToday] = useState(new Date().toISOString().slice(0, 10));
  const [err, setErr] = useState("");
  const [drag, setDrag] = useState(false);

  const run = async () => {
    if (!files.length) return;
    setErr("");
    try { setJob({ id: await api.uploadReview(files, today), status: "pending" }); }
    catch (e: any) { if (e.message === "unauthorized") onLogout(); else setErr(e.message); }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDrag(false);
    const dropped = Array.from(e.dataTransfer.files || []);
    if (dropped.length) setFiles(dropped);
  };

  return (
    <div>
      <PageHeader title="품질검토" subtitle="입점 서류(zip 또는 개별 파일)를 업로드하면 인허가·영양성분·자가품질을 자동 검토합니다." right="홈 › 품질검토" />

      <div className="mb-6 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <label
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={onDrop}
          className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition ${
            drag ? "border-brand-600 bg-brand-50" : "border-slate-300 hover:border-brand-600 hover:bg-slate-50"
          }`}
        >
          <span className="text-3xl">📂</span>
          <span className="text-sm font-medium text-slate-700">파일을 여기로 드래그하거나 클릭해서 선택</span>
          <span className="text-xs text-slate-400">zip · PDF · 이미지 · HWP/HWPX · XLSX (다중 가능)</span>
          <input
            type="file"
            multiple
            accept=".zip,.pdf,.png,.jpg,.jpeg,.webp,.tiff,.bmp,.gif,.hwp,.hwpx,.docx,.xlsx,.xls"
            onChange={(e) => setFiles(Array.from(e.target.files || []))}
            className="hidden"
          />
        </label>
        {files.length > 0 && (
          <div className="mt-3 text-sm text-slate-600">선택됨: {files.map((f) => f.name).join(", ")}</div>
        )}
        <div className="mt-3 flex items-center gap-3">
          <label className="text-sm text-slate-600">기준일</label>
          <input type="date" value={today} onChange={(e) => setToday(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1 text-sm" />
          <button onClick={run} disabled={!files.length} className="ml-auto rounded-lg bg-brand-600 px-5 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50">검토 실행</button>
        </div>
        {err && <p className="mt-2 text-sm text-rose-600">{err}</p>}
      </div>

      {job && job.status !== "done" && (
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          {job.status === "error" ? (
            <span className="text-rose-600">오류: {job.error}</span>
          ) : (
            <ReviewProgress job={job} />
          )}
        </div>
      )}

      {job?.status === "done" && job.result && <ReviewResult report={job.result} />}
    </div>
  );
}
