// 백엔드(FastAPI) 호출 래퍼. dev 에서는 vite 프록시(/api → :8800).
const BASE = import.meta.env.VITE_API_BASE || "/api";

const TOKEN_KEY = "qr_token";
export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

// 401(세션 만료/무효 토큰)이면 토큰을 비우고 명확한 오류를 던진다 → 화면이 "검색안됨"으로 조용히 끝나지 않게
function check401(status: number) {
  if (status === 401) {
    clearToken();
    throw new Error("세션이 만료되었습니다. 로그아웃 후 다시 로그인해주세요.");
  }
}

export async function login(username: string, password: string): Promise<void> {
  const body = new FormData();
  body.append("username", username);
  body.append("password", password);
  const r = await fetch(`${BASE}/auth/login`, { method: "POST", body });
  if (!r.ok) throw new Error("아이디 또는 비밀번호가 올바르지 않습니다");
  const data = await r.json();
  setToken(data.access_token);
}

export async function uploadReview(files: File[], today?: string): Promise<string> {
  const body = new FormData();
  files.forEach((f) => body.append("files", f));
  if (today) body.append("today", today);
  const r = await fetch(`${BASE}/reviews`, { method: "POST", headers: authHeaders(), body });
  if (r.status === 401) throw new Error("unauthorized");
  if (!r.ok) throw new Error("업로드 실패");
  return (await r.json()).job_id;
}

export async function getReview(jobId: string): Promise<any> {
  const r = await fetch(`${BASE}/reviews/${jobId}`, { headers: authHeaders() });
  if (r.status === 401) throw new Error("unauthorized");
  if (!r.ok) throw new Error("조회 실패");
  return r.json();
}

export async function listReviews(): Promise<any[]> {
  const r = await fetch(`${BASE}/reviews`, { headers: authHeaders() });
  if (!r.ok) return [];
  return (await r.json()).jobs || [];
}

export async function getAgencies(): Promise<any> {
  const r = await fetch(`${BASE}/agencies`, { headers: authHeaders() });
  check401(r.status);
  if (!r.ok) return null;
  return r.json();
}

export async function listAgencies(q = "", category = ""): Promise<any> {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (category) params.set("category", category);
  const r = await fetch(`${BASE}/agencies/list?${params}`, { headers: authHeaders() });
  check401(r.status);
  if (!r.ok) return { count: 0, items: [] };
  return r.json();
}

export async function getLaws(): Promise<any> {
  const r = await fetch(`${BASE}/laws`, { headers: authHeaders() });
  check401(r.status);
  if (!r.ok) return { items: [] };
  return r.json();
}

export async function searchBusiness(filters: {
  q?: string; license_no?: string; industry?: string; address?: string;
}): Promise<any> {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  if (filters.license_no) params.set("license_no", filters.license_no);
  if (filters.industry) params.set("industry", filters.industry);
  if (filters.address) params.set("address", filters.address);
  const r = await fetch(`${BASE}/business/search?${params}`, { headers: authHeaders() });
  check401(r.status);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "업체 검색 실패");
  return r.json();
}

export async function getLawBody(seq: string, target = "eflaw"): Promise<any> {
  const r = await fetch(`${BASE}/laws/body?seq=${encodeURIComponent(seq)}&target=${target}`, {
    headers: authHeaders(),
  });
  check401(r.status);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "본문 조회 실패");
  return r.json();
}

export async function getFoodSpec(productType: string): Promise<any> {
  const r = await fetch(`${BASE}/foodcode/spec?product_type=${encodeURIComponent(productType)}`, {
    headers: authHeaders(),
  });
  check401(r.status);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "식품공전 조회 실패");
  return r.json();
}

export async function getLawAttachment(link: string): Promise<any> {
  const r = await fetch(`${BASE}/laws/attachment?link=${encodeURIComponent(link)}`, {
    headers: authHeaders(),
  });
  check401(r.status);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "첨부파일 변환 실패");
  return r.json();
}
