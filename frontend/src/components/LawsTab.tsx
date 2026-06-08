import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import * as api from "../api";

const STATUS_STYLE: Record<string, string> = {
  현행: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  시행예정: "bg-amber-50 text-amber-800 ring-amber-600/20",
  미수집: "bg-slate-100 text-slate-500 ring-slate-400/20",
};

function fmtDate(d?: string) {
  if (!d || d.length < 8) return d || "";
  return `${d.slice(0, 4)}. ${d.slice(4, 6)}. ${d.slice(6, 8)}.`;
}

export default function LawsTab() {
  const [items, setItems] = useState<any[]>([]);
  const [note, setNote] = useState("");
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<"law" | "admrul">("law");
  const [sel, setSel] = useState<any>(null);

  useEffect(() => { api.getLaws().then((d) => { setItems(d.items || []); setNote(d.note || ""); }); }, []);

  const filtered = useMemo(
    () => items.filter((l) => l.kind === kind && (!q || l.name.replace(/\s/g, "").includes(q.replace(/\s/g, "")))),
    [items, kind, q]
  );

  if (sel) return <LawDetail law={sel} onBack={() => setSel(null)} />;

  return (
    <div>
      {/* 헤더 */}
      <div className="mb-5 flex items-end justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">법령·규제</h2>
          <p className="text-sm text-slate-500">식약처 식품 관련 현행 법령과 행정규칙 · 현행/시행예정 모니터링</p>
        </div>
        <div className="text-xs text-slate-400">홈 › 법령·규제</div>
      </div>

      {/* 검색바 */}
      <div className="mb-4 flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 shadow-sm">
        <span className="text-slate-400">🔍</span>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="법령명으로 검색하세요" className="w-full text-sm outline-none" />
      </div>

      {/* 탭 */}
      <div className="mb-3 grid grid-cols-2 overflow-hidden rounded-xl border border-slate-200">
        {([["law", "중앙부처 법령"], ["admrul", "행정규칙"]] as const).map(([k, label]) => (
          <button
            key={k}
            onClick={() => setKind(k)}
            className={`py-2.5 text-sm font-semibold ${kind === k ? "bg-brand-600 text-white" : "bg-white text-slate-500 hover:bg-slate-50"}`}
          >
            {label}
          </button>
        ))}
      </div>

      {note && <div className="mb-3 rounded-lg bg-brand-50 px-4 py-2 text-xs text-brand-700 ring-1 ring-inset ring-brand-600/20">ℹ️ {note}</div>}
      <div className="mb-2 text-sm text-slate-500">총 <b className="text-slate-800">{filtered.length}</b>건</div>

      {/* 목록 */}
      <div className="divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white shadow-sm">
        {filtered.map((law, i) => (
          <button
            key={law.seq || law.name || i}
            onClick={() => law.seq && setSel(law)}
            className={`block w-full px-5 py-4 text-left ${law.seq ? "hover:bg-slate-50" : "cursor-default opacity-70"}`}
          >
            <div className="mb-1 flex items-center gap-2">
              <span className="rounded bg-brand-50 px-1.5 py-0.5 text-[11px] font-medium text-brand-700">{law.kind === "law" ? "법령" : "행정규칙"}</span>
              <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-500">식품의약품안전처</span>
              <span className={`ml-auto rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${STATUS_STYLE[law.status] || STATUS_STYLE["미수집"]}`}>{law.status}</span>
            </div>
            <div className="text-base font-semibold text-slate-900">{law.name}</div>
            <div className="mt-1 flex flex-wrap gap-x-5 gap-y-0.5 text-xs text-slate-500">
              {law.enforce_date && <span>시행일 : {fmtDate(law.enforce_date)}</span>}
              {law.promulgation_date && <span>공포일 : {fmtDate(law.promulgation_date)}</span>}
              {law.revision_type && <span>개정유형 : {law.revision_type}</span>}
              {law.upcoming_enforce_date && <span className="text-amber-700">🗓 시행예정 {fmtDate(law.upcoming_enforce_date)}</span>}
            </div>
          </button>
        ))}
        {filtered.length === 0 && <div className="px-5 py-10 text-center text-sm text-slate-400">결과 없음</div>}
      </div>
    </div>
  );
}

function LawDetail({ law, onBack }: { law: any; onBack: () => void }) {
  const [body, setBody] = useState<any>(null);
  const [err, setErr] = useState("");
  const [att, setAtt] = useState<string | null>(null);
  const [attLoading, setAttLoading] = useState(false);
  const [attErr, setAttErr] = useState("");
  // 현행 ↔ 시행예정 ↔ 신구대비 전환 (시행예정 버전이 있을 때만)
  const [view, setView] = useState<"current" | "upcoming" | "diff">("current");
  const viewSeq = view === "upcoming" && law.upcoming_seq ? law.upcoming_seq : law.seq;
  useEffect(() => {
    if (view === "diff") return; // 신구대비는 DiffView 가 자체적으로 양쪽을 불러온다
    setBody(null); setErr(""); setAtt(null); setAttErr("");
    api.getLawBody(viewSeq, law.kind === "admrul" ? "admrul" : "eflaw").then(setBody).catch((e) => setErr(e.message));
  }, [viewSeq, view]);

  // 고시전문 첨부(HWPX/HWP/ZIP)를 마크다운으로 변환해 본문으로 렌더
  const loadAttachment = (link: string) => {
    setAttLoading(true); setAttErr("");
    api.getLawAttachment(link)
      .then((d) => setAtt(d.markdown || "(변환 결과 없음)"))
      .catch((e) => setAttErr(e.message))
      .finally(() => setAttLoading(false));
  };

  // 조문이 없고 고시전문 첨부만 있는 고시는 본문을 자동 변환·표시
  // (백엔드가 flSeq 기준으로 캐시 → 최초 1회만 변환, 개정 시 새 flSeq 로 자동 재변환)
  useEffect(() => {
    if (view === "diff") return;
    if (body && body.articles?.length === 0 && body.attachments?.length && att === null && !attLoading) {
      loadAttachment(body.attachments[0].link);
    }
  }, [body, view]);

  return (
    <div>
      <div className="mb-3 flex items-center justify-between text-sm">
        <button onClick={onBack} className="flex items-center gap-1 text-slate-500 hover:text-slate-800">‹ 목록으로</button>
        <span className="text-xs text-slate-400">{law.kind === "law" ? "중앙부처 법령" : "행정규칙"} › 상세</span>
      </div>

      <div className="mb-1 flex items-center gap-2">
        <span className="rounded bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700">{law.kind === "law" ? "법령" : "행정규칙"}</span>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${STATUS_STYLE[law.status] || STATUS_STYLE["미수집"]}`}>{law.status}</span>
      </div>
      <h1 className="text-2xl font-bold text-slate-900">{law.name}</h1>
      <div className="mt-1.5 flex flex-wrap gap-x-5 text-sm text-slate-500">
        {law.enforce_date && <span>시행일 : <b className="text-slate-700">{fmtDate(law.enforce_date)}</b></span>}
        {law.promulgation_date && <span>공포일 : <b className="text-slate-700">{fmtDate(law.promulgation_date)}</b></span>}
        {law.revision_type && <span>구분 : <b className="text-slate-700">{law.revision_type}</b></span>}
        <span>소관부처 : <b className="text-slate-700">식품의약품안전처</b></span>
        {law.upcoming_enforce_date && <span className="text-amber-700">🗓 시행예정 {fmtDate(law.upcoming_enforce_date)}</span>}
      </div>

      {law.upcoming_seq && (
        <div className="mt-3 inline-flex overflow-hidden rounded-lg border border-slate-200 text-sm">
          {([["current", "현행"], ["upcoming", `시행예정${law.upcoming_enforce_date ? " (" + fmtDate(law.upcoming_enforce_date) + ")" : ""}`], ["diff", "🆚 신구대비"]] as const).map(([k, label]) => (
            <button
              key={k}
              onClick={() => setView(k)}
              className={`px-4 py-1.5 font-semibold ${view === k ? "bg-brand-600 text-white" : "bg-white text-slate-500 hover:bg-slate-50"}`}
            >
              {label}
            </button>
          ))}
        </div>
      )}
      <div className="my-4 border-b-2 border-slate-800" />

      {view === "diff" && (
        <DiffView
          currentSeq={law.seq}
          upcomingSeq={law.upcoming_seq}
          target={law.kind === "admrul" ? "admrul" : "eflaw"}
        />
      )}

      {view !== "diff" && err && <p className="text-sm text-rose-600">본문 조회 실패: {err}</p>}
      {view !== "diff" && !body && !err && <p className="text-sm text-slate-400">본문 불러오는 중…</p>}

      {view !== "diff" && body && (
        <div className="flex gap-6">
          {/* 본문 */}
          <div className="min-w-0 flex-1 space-y-8">
            <Section roman="I" title="본문" id="sec-body">
              {body.articles.length > 0 ? (
                <div className="space-y-4">
                  {body.articles.map((a: any, i: number) =>
                    a.type === "head" ? (
                      <h3 id={`a${i}`} key={i} className={headClass(a.level)}>{a.text}</h3>
                    ) : (
                      <div id={`a${i}`} key={i} className="scroll-mt-4">
                        <div className="mb-1 font-bold text-slate-900">{artLabel(a)}</div>
                        <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">{artBody(a)}</p>
                      </div>
                    )
                  )}
                </div>
              ) : body.attachments?.length ? (
                att !== null ? (
                  <AttachmentBody md={att} />
                ) : attErr ? (
                  <div className="rounded-lg border border-rose-200 bg-rose-50 p-5 text-sm text-rose-700">
                    <p className="mb-2">본문 변환 실패: {attErr}</p>
                    <button onClick={() => loadAttachment(body.attachments[0].link)} className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700">다시 시도</button>
                  </div>
                ) : (
                  <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 p-5 text-sm text-slate-600">
                    <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600" />
                    고시전문(첨부파일) 본문을 불러오는 중… (최초 1회만 변환, 식품공전은 다소 소요)
                  </div>
                )
              ) : (
                <p className="text-sm text-slate-400">본문 조문 없음</p>
              )}
            </Section>

            <Section roman="II" title="부칙" id="sec-addenda">
              <div className="space-y-3">
                {body.addenda.map((b: any, i: number) => (
                  <div key={i} className="rounded-lg bg-slate-50 p-3">
                    <div className="mb-1 text-xs text-slate-500">
                      {b.promul_no && <span className="mr-2 rounded bg-brand-50 px-1.5 py-0.5 font-medium text-brand-700">공포번호 {b.promul_no}</span>}
                      {fmtDate(b.date)}
                    </div>
                    <div className="whitespace-pre-wrap text-sm text-slate-700">{b.content}</div>
                  </div>
                ))}
                {body.addenda.length === 0 && <p className="text-sm text-slate-400">부칙 없음</p>}
              </div>
            </Section>

            <Section roman="III" title="별표·서식 / 별지·별첨" id="sec-tables">
              {(() => {
                // 삭제된 빈 항목(파일 없음 + '삭제' 제목)은 제외하고, 별표/서식(별지)으로 분리.
                const live = (body.tables || []).filter((t: any) => !( (t.title || "").startsWith("삭제") && !t.hwp && !t.pdf ));
                if (live.length === 0) return <p className="text-sm text-slate-400">별표·서식 없음 (별표는 주로 시행규칙·고시에 포함)</p>;
                const groups: [string, any[]][] = [
                  ["별표", live.filter((t: any) => (t.gubun || "별표") === "별표")],
                  ["서식(별지)", live.filter((t: any) => (t.gubun || "") === "서식")],
                ];
                const row = (t: any, label: string, i: number) => (
                  <li key={`${label}-${i}`} className="flex items-center justify-between rounded-lg border border-slate-200 px-4 py-2.5 text-sm">
                    <span className="text-slate-700">{t.no ? `[${label} ${t.no}] ` : ""}{t.title || label}</span>
                    <span className="flex gap-2 text-xs">
                      {t.hwp && <a href={t.hwp} target="_blank" rel="noreferrer" className="rounded bg-slate-900 px-2.5 py-1 text-white hover:bg-slate-700">📄 HWP</a>}
                      {t.pdf && <a href={t.pdf} target="_blank" rel="noreferrer" className="rounded bg-rose-600 px-2.5 py-1 text-white hover:bg-rose-500">📕 PDF</a>}
                    </span>
                  </li>
                );
                return groups.filter(([, list]) => list.length > 0).map(([label, list]) => (
                  <div key={label} id={label === "서식(별지)" ? "sec-서식" : "sec-별표"} className="mb-4 scroll-mt-4">
                    <div className="mb-1.5 text-sm font-semibold text-slate-500">{label} <span className="font-normal text-slate-400">{list.length}건</span></div>
                    <ul className="space-y-2">{list.map((t: any, i: number) => row(t, label === "서식(별지)" ? "서식" : "별표", i))}</ul>
                  </div>
                ));
              })()}
            </Section>
          </div>

          {/* 우측 체계 네비게이션 (장·절·조 → 부칙 → 별표) — 스크롤 따라다니도록 sticky */}
          <nav className="sticky top-4 hidden max-h-[calc(100vh-2rem)] w-60 shrink-0 self-start overflow-auto lg:block">
            <div className="rounded-xl border border-slate-200 bg-white p-3 text-sm shadow-sm">
              <div className="mb-2 border-b border-slate-100 pb-1.5 font-semibold text-slate-700">법령 체계</div>
              {body.articles.length === 0 && att ? (
                /* 고시전문 첨부(식품공전 등): 파트를 본문/별표·서식/부칙으로 구분 */
                attGroups(att).map((g) => (
                  <div key={g.label} className="mb-1.5">
                    <div className="mt-2 border-t border-slate-100 pt-1.5 font-semibold text-slate-700">{g.label}</div>
                    {g.items.map((t, i) => (
                      <button key={i} onClick={() => scrollTo(attSlug(t))} className="block w-full truncate py-0.5 pl-3 text-left text-xs text-slate-500 hover:text-brand-700">{t}</button>
                    ))}
                  </div>
                ))
              ) : (
                <>
                  {body.articles.map((a: any, i: number) =>
                    a.type === "head" ? (
                      <button key={i} onClick={() => scrollTo(`a${i}`)} className={`block w-full truncate py-0.5 text-left font-semibold text-slate-800 hover:text-brand-700 ${a.level >= 2 ? "pl-3" : ""}`}>{a.text}</button>
                    ) : (
                      <button key={i} onClick={() => scrollTo(`a${i}`)} className="block w-full truncate py-0.5 pl-4 text-left text-xs text-slate-500 hover:text-brand-700">{artNo(a)} {a.title || ""}</button>
                    )
                  )}
                  <div className="mt-2 border-t border-slate-100 pt-1.5">
                    <button onClick={() => scrollTo("sec-addenda")} className="block w-full py-0.5 text-left font-semibold text-slate-700 hover:text-brand-700">부칙</button>
                    {(() => {
                      const tb = body.tables || [];
                      const hasByul = tb.some((t: any) => (t.gubun || "별표") === "별표");
                      const hasSeo = tb.some((t: any) => (t.gubun || "") === "서식");
                      return (
                        <>
                          <button onClick={() => scrollTo("sec-tables")} className="block w-full py-0.5 text-left font-semibold text-slate-700 hover:text-brand-700">별표·서식</button>
                          {hasByul && <button onClick={() => scrollTo("sec-별표")} className="block w-full py-0.5 pl-3 text-left text-xs text-slate-500 hover:text-brand-700">└ 별표</button>}
                          {hasSeo && <button onClick={() => scrollTo("sec-서식")} className="block w-full py-0.5 pl-3 text-left text-xs text-slate-500 hover:text-brand-700">└ 서식(별지)</button>}
                        </>
                      );
                    })()}
                  </div>
                </>
              )}
            </div>
          </nav>
        </div>
      )}
    </div>
  );
}

function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

// 고시전문 첨부 본문 — 여러 파트(제1~제5, 별표 등)면 상단에 '파트 이동' 네비를 붙인다
function attSlug(t: string): string {
  return "att-" + t.trim().replace(/\s+/g, "-").replace(/[^가-힣\w-]/g, "").slice(0, 48);
}
function nodeText(c: any): string {
  if (typeof c === "string") return c;
  if (Array.isArray(c)) return c.map(nodeText).join("");
  if (c?.props?.children) return nodeText(c.props.children);
  return "";
}
function attHeadings(md: string): string[] {
  return Array.from(md.matchAll(/^#\s+(.+)$/gm), (m) => m[1].trim());
}
// 파트 제목으로 본문/별표/부칙 구분 (식품공전: (1)~(4) 본문, (5)~(8) 별표, (9) 부칙)
function attCategory(t: string): "본문" | "별표·서식" | "부칙" {
  if (/부칙/.test(t)) return "부칙";
  if (/별표|별지|서식|일람표/.test(t)) return "별표·서식";
  return "본문";
}
function attGroups(md: string): { label: string; items: string[] }[] {
  const heads = attHeadings(md);
  const order = ["본문", "별표·서식", "부칙"] as const;
  return order
    .map((label) => ({ label, items: heads.filter((h) => attCategory(h) === label) }))
    .filter((g) => g.items.length > 0);
}
function AttachmentBody({ md }: { md: string }) {
  // 파트 헤더(h1)에 id 부여 → 우측 '법령 체계' 네비에서 스크롤 이동
  return (
    <div className="lawdoc">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw]}
        components={{ h1: ({ children }) => <h1 id={attSlug(nodeText(children))} className="scroll-mt-4">{children}</h1> }}
      >
        {md}
      </ReactMarkdown>
    </div>
  );
}

// 단어 단위 LCS diff — 현행/시행예정에서 달라진 토큰만 강조
function diffTokens(a: string[], b: string[]) {
  const m = a.length, n = b.length;
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = m - 1; i >= 0; i--)
    for (let j = n - 1; j >= 0; j--)
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const oldParts: { t: string; c: boolean }[] = [];
  const newParts: { t: string; c: boolean }[] = [];
  let i = 0, j = 0;
  while (i < m && j < n) {
    if (a[i] === b[j]) { oldParts.push({ t: a[i], c: false }); newParts.push({ t: b[j], c: false }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { oldParts.push({ t: a[i], c: true }); i++; }
    else { newParts.push({ t: b[j], c: true }); j++; }
  }
  while (i < m) oldParts.push({ t: a[i++], c: true });
  while (j < n) newParts.push({ t: b[j++], c: true });
  return { oldParts, newParts };
}

// 공백을 보존하며 토큰화
function tokenize(s: string): string[] {
  return s.split(/(\s+)/).filter((t) => t !== "");
}

function DiffText({ oldText, newText, side }: { oldText: string; newText: string; side: "old" | "new" }) {
  const { oldParts, newParts } = useMemo(
    () => diffTokens(tokenize(oldText), tokenize(newText)),
    [oldText, newText]
  );
  const parts = side === "old" ? oldParts : newParts;
  return (
    <>
      {parts.map((p, i) =>
        p.c ? (
          side === "old" ? (
            <del key={i} className="bg-rose-100 text-rose-700 decoration-rose-400">{p.t}</del>
          ) : (
            <mark key={i} className="rounded bg-amber-200 px-0.5">{p.t}</mark>
          )
        ) : (
          <span key={i}>{p.t}</span>
        )
      )}
    </>
  );
}

// 신구조문 대비 — 현행/시행예정 본문을 조문 단위로 매칭해 달라진 조문만 좌우 비교
function DiffView({ currentSeq, upcomingSeq, target }: { currentSeq: string; upcomingSeq: string; target: string }) {
  const [cur, setCur] = useState<any>(null);
  const [up, setUp] = useState<any>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let alive = true;
    setErr(""); setCur(null); setUp(null);
    // 법제처는 동시 호출 시 연결을 끊는 경우가 있어 순차로 받는다
    (async () => {
      try {
        const c = await api.getLawBody(currentSeq, target);
        if (!alive) return;
        setCur(c);
        const u = await api.getLawBody(upcomingSeq, target);
        if (!alive) return;
        setUp(u);
      } catch (e: any) {
        if (alive) setErr(e.message);
      }
    })();
    return () => { alive = false; };
  }, [currentSeq, upcomingSeq]);

  if (err) return <p className="text-sm text-rose-600">신구대비 조회 실패: {err}</p>;
  if (!cur || !up) return <p className="text-sm text-slate-400">현행·시행예정 본문 비교 중…</p>;

  const keyOf = (a: any) => `${a.no || ""}-${a.branch || ""}`;
  const curMap = new Map<string, any>();
  const upMap = new Map<string, any>();
  cur.articles.filter((a: any) => a.type === "article").forEach((a: any) => curMap.set(keyOf(a), a));
  up.articles.filter((a: any) => a.type === "article").forEach((a: any) => upMap.set(keyOf(a), a));
  const norm = (s?: string) => (s || "").replace(/\s+/g, " ").trim();

  // 합집합 키를 조문번호 순으로 정렬, 내용이 다른(또는 신설/삭제) 조문만 추림.
  // 조문번호가 숫자가 아닐 수 있으므로(별표 등) NaN 가드 후 문자열 비교로 폴백.
  const numOr = (v: string) => { const n = Number(v); return Number.isNaN(n) ? null : n; };
  const keys = Array.from(new Set([...curMap.keys(), ...upMap.keys()])).sort((a, b) => {
    const [an, ab] = a.split("-"); const [bn, bb] = b.split("-");
    const na = numOr(an), nb = numOr(bn);
    if (na === null || nb === null) return a.localeCompare(b);
    return na - nb || (numOr(ab) || 0) - (numOr(bb) || 0);
  });
  const diffs = keys
    .map((k) => ({ k, c: curMap.get(k), u: upMap.get(k) }))
    .filter(({ c, u }) => norm(c?.content) !== norm(u?.content));

  return (
    <div>
      <div className="mb-4 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-900 ring-1 ring-inset ring-amber-600/20">
        🆚 현행과 시행예정 본문을 조문 단위로 비교했습니다. 달라진 조문 <b>{diffs.length}</b>건 (신설·삭제·개정 포함)
      </div>
      {diffs.length === 0 ? (
        <p className="text-sm text-slate-400">조문 본문상의 차이가 없습니다 (부칙·별표 등 비교 대상 외 변경일 수 있음).</p>
      ) : (
        <div className="space-y-4">
          {diffs.map(({ k, c, u }) => {
            const added = !c, removed = !u;
            return (
              <div key={k} className="overflow-hidden rounded-xl border border-slate-200">
                <div className="flex items-center gap-2 border-b border-slate-100 bg-slate-50 px-4 py-2 text-sm font-semibold text-slate-700">
                  {artLabel(u || c)}
                  {added && <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-700">신설</span>}
                  {removed && <span className="rounded-full bg-rose-100 px-2 py-0.5 text-xs text-rose-700">삭제</span>}
                  {!added && !removed && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800">개정</span>}
                </div>
                <div className="grid grid-cols-2 divide-x divide-slate-100 text-sm">
                  <div className="px-4 py-3">
                    <div className="mb-1 text-xs font-semibold text-slate-400">현행</div>
                    <p className="whitespace-pre-wrap leading-relaxed text-slate-700">
                      {removed ? artBody(c) : <DiffText oldText={artBody(c)} newText={artBody(u)} side="old" />}
                    </p>
                  </div>
                  <div className="bg-amber-50/30 px-4 py-3">
                    <div className="mb-1 text-xs font-semibold text-amber-700">시행예정</div>
                    <p className="whitespace-pre-wrap leading-relaxed text-slate-800">
                      {added ? <mark className="rounded bg-amber-200 px-0.5">{artBody(u)}</mark> : <DiffText oldText={artBody(c)} newText={artBody(u)} side="new" />}
                    </p>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function headClass(level: number): string {
  const size = level === 0 ? "text-2xl" : level === 1 ? "text-xl" : level === 2 ? "text-lg" : "text-base";
  return `scroll-mt-4 ${size} font-extrabold text-slate-900 mt-6 mb-1 border-b border-slate-200 pb-1`;
}

function artNo(a: any): string {
  return `제${a.no}조${a.branch ? `의${a.branch}` : ""}`;
}

function artLabel(a: any): string {
  if (!a) return "";
  return a.title ? `${artNo(a)}(${a.title})` : artNo(a);
}

function artBody(a: any): string {
  // 조문내용 앞의 '제N조(제목)' 표제를 제거하고 본문만 남김
  return (a?.content || "").replace(/^제\s*\d+조(의\d+)?\s*(\([^)]*\))?\s*/, "").replace(/^\s+/, "");
}

function Section({ roman, title, id, children }: { roman: string; title: string; id?: string; children: React.ReactNode }) {
  return (
    <section id={id} className="scroll-mt-4">
      <div className="mb-4 flex items-center gap-2 border-b border-slate-200 pb-2">
        <span className="text-lg font-bold text-brand-600">{roman}.</span>
        <h2 className="text-lg font-bold text-slate-800">{title}</h2>
      </div>
      {children}
    </section>
  );
}
