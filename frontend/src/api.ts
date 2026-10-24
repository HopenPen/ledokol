// Тонкий клиент к FastAPI. Токен держим в памяти вкладки (не в localStorage): закрыл вкладку — вышел.
// Для демо этого достаточно; в бою вход идёт через авторизацию банка.

export interface Point { date: string; p10: number; p50: number; p90: number; prob_below: number }
export interface FutureEvent {
  date: string; amount: number; direction: 'in' | 'out'; title: string; category: string
  source: 'history' | 'calendar' | 'manual' | '1c' | 'scenario'; probability: number
}
export interface Alert {
  start: string; end: string; probability: number; level: string; shortfall: number; worst_case: boolean
  explanation: string; causes: FutureEvent[]; actions: string[]
}
export interface Forecast {
  as_of: string; last_balance: number; threshold: number; headline: string; low_history: boolean
  warnings: string[]; points: Point[]; events: FutureEvent[]; alerts: Alert[]
}
export interface Company { id: string; external_id: string; name: string; industry: string | null; tax_regime: string; min_balance: string }
export interface Dashboard {
  company: Company; forecast: Forecast; history: { date: string; balance: number }[]
  top_clients: { counterparty_key: string; name: string; share: number }[]; model_version: string
}
export interface EventRow { id: string; event_date: string; amount: string; direction: string; kind: string; source: string; title: string; confidence: string; status: string }
export interface Operation { id: string; op_date: string; amount: string; direction: string; counterparty_name: string; purpose: string; category: string; category_label: string; category_source: string; quality: string }
export interface PlanFactRow { event_id: string | null; title: string; planned_date: string; planned_amount: number; status: string; actual_amount: number; actual_date: string | null }
export interface ScenarioResult { base: Forecast; scenario: Forecast; delta: { base_first_gap: string | null; scenario_first_gap: string | null; base_min_p50: number; scenario_min_p50: number; extra_shortfall: number } }

let token: string | null = null
export const isLoggedIn = () => token !== null
export const logout = () => { token = null }

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

async function request<T>(method: string, path: string, body?: unknown, headers: Record<string, string> = {}): Promise<T> {
  const init: RequestInit = { method, headers: { ...headers } }
  if (token) (init.headers as Record<string, string>).Authorization = `Bearer ${token}`
  if (body instanceof FormData) init.body = body
  else if (body !== undefined) {
    (init.headers as Record<string, string>)['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }
  const resp = await fetch(path, init)
  if (resp.status === 401) logout()
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}))
    throw new ApiError(resp.status, typeof detail.detail === 'string' ? detail.detail : 'Не удалось выполнить запрос')
  }
  return resp.status === 204 ? (undefined as T) : resp.json()
}

export const api = {
  async login(login: string, password: string) {
    const r = await request<{ access_token: string }>('POST', '/api/auth/login', { login, password })
    token = r.access_token
  },
  companies: () => request<Company[]>('GET', '/api/companies'),
  importStatement: (file: File) => { const f = new FormData(); f.append('file', file); return request<{ company: Company; rows_new: number }[]>('POST', '/api/companies/import', f) },
  uploadStatement: (id: string, file: File) => { const f = new FormData(); f.append('file', file); return request('POST', `/api/companies/${id}/statements`, f) },
  dashboard: (id: string) => request<Dashboard>('GET', `/api/companies/${id}/dashboard`),
  forecast: (id: string, horizon: number) => request<Forecast>('GET', `/api/companies/${id}/forecast?horizon=${horizon}`),
  patchCompany: (id: string, body: Partial<{ name: string; industry: string; tax_regime: string; min_balance: string }>) => request<Company>('PATCH', `/api/companies/${id}`, body),
  events: (id: string) => request<EventRow[]>('GET', `/api/companies/${id}/events`),
  // Idempotency-Key создаётся один раз на открытие формы: двойной клик не создаст два события.
  addEvent: (id: string, body: object, idemKey: string) => request<EventRow>('POST', `/api/companies/${id}/events`, body, { 'Idempotency-Key': idemKey }),
  deleteEvent: (id: string, eventId: string) => request<void>('DELETE', `/api/companies/${id}/events/${eventId}`),
  scenario: (id: string, body: object) => request<ScenarioResult>('POST', `/api/companies/${id}/scenarios`, body),
  operations: (id: string, offset = 0, category = '') => request<Operation[]>('GET', `/api/companies/${id}/operations?limit=100&offset=${offset}${category ? `&category=${category}` : ''}`),
  categories: () => request<{ code: string; label: string }[]>('GET', '/meta/categories'),
  patchCategory: (opId: string, category: string, applyToCounterparty: boolean) => request<Operation[]>('PATCH', `/api/operations/${opId}/category`, { category, apply_to_counterparty: applyToCounterparty }),
  planFact: (id: string) => request<PlanFactRow[]>('GET', `/api/companies/${id}/plan-fact`),
  sync1c: (id: string) => request<{ created: number; updated: number; closed: number }>('POST', `/api/companies/${id}/sync/1c`),
  syncFns: (id: string) => request<{ inn: string; status: string; has_tax_debt: boolean; risky: boolean }[]>('POST', `/api/companies/${id}/sync/fns`),
  ask: (id: string, question: string) => request<{ answer: string; generated_by: string }>('POST', `/api/companies/${id}/assistant/ask`, { question }),
}
