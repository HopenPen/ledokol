// Тонкий клиент к FastAPI. Токен — в sessionStorage: F5 не разлогинивает, закрыл вкладку — вышел.
// localStorage не используем: токен жил бы бессрочно и был бы виден всем вкладкам. В бою — вход через банк.

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
  missed_payments: EventRow[]
}
export interface DayCompare { date: string; plan: number; low: number; high: number; fact: number; deviation: number; flagged: boolean }
export interface DailyPlanFact { run: { id: string; as_of: string; model_version: string } | null; rows: DayCompare[]; flagged_days: number }
export interface EventRow { id: string; event_date: string; amount: string; direction: string; kind: string; source: string; title: string; confidence: string; status: string }
export interface Operation { id: string; op_date: string; amount: string; direction: string; counterparty_name: string; purpose: string; category: string; category_label: string; category_source: string; quality: string; counterparty_inn: string | null; balance_eod: string | null; source: 'manual' | 'statement' }
export interface ImportResult { company: Company; rows_total: number; rows_new: number; rows_matched: number; already_imported: boolean; quality: { rows_rejected: number; rows_total: number; duplicates: number; balance_jumps: number; empty_purpose: number; empty_inn: number; history_working_days: number; warnings: string[] } }
export interface RegistrationInfo { email_delivery: 'disabled' | 'unavailable' | 'local' | 'smtp'; local_mailbox_url: string | null }
export interface PaymentInput { op_date: string; amount: string; direction: 'in' | 'out'; counterparty_name: string; counterparty_inn: string }
export interface AccountBalance {
  amount: string | null; as_of: string | null; source: 'unknown' | 'initial' | 'statement' | 'legacy' | 'calculated'
  anchor_date: string | null; anchor_source: 'initial' | 'statement' | 'legacy' | null
  initial_date: string | null; initial_amount: string | null; first_operation_date: string | null; unknown_operations: number
}
export interface PlanFactRow { event_id: string | null; title: string; planned_date: string; planned_amount: number; status: string; actual_amount: number; actual_date: string | null }
export interface Attachment { id: string; operation_id: string; kind: 'receipt' | 'related'; filename: string; content_type: string; size_bytes: number; previewable: boolean; created_at: string }
export interface ScenarioResult { base: Forecast; scenario: Forecast; delta: { base_first_gap: string | null; scenario_first_gap: string | null; base_min_p50: number; scenario_min_p50: number; extra_shortfall: number } }

const TOKEN_KEY = 'cashflow.token'
function readToken(): string | null {
  try { return sessionStorage.getItem(TOKEN_KEY) } catch { return null }   // приватный режим может запрещать storage
}
let token: string | null = readToken()
function setToken(t: string | null) {
  token = t
  try { t ? sessionStorage.setItem(TOKEN_KEY, t) : sessionStorage.removeItem(TOKEN_KEY) } catch { /* работаем из памяти */ }
}
export const isLoggedIn = () => token !== null
// Вход через банк появится на бэкенде позже: адрес задаётся при сборке, пока его нет — кнопка неактивна.
export const SSO_CENTRINVEST_URL: string = import.meta.env.VITE_SSO_CENTRINVEST_URL ?? ''
export const logout = () => {
  setToken(null)
  try {
    Object.keys(sessionStorage).filter(key => key.startsWith('cashflow.chat.')).forEach(key => sessionStorage.removeItem(key))
  } catch { /* storage may be unavailable */ }
}

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
    const message = typeof detail.detail === 'string' ? detail.detail : Array.isArray(detail.detail)
      ? detail.detail.map((e: { loc?: string[]; msg: string }) => `${e.loc?.slice(1).join('.')}: ${e.msg}`).join('; ')
      : 'Не удалось выполнить запрос'
    throw new ApiError(resp.status, message)
  }
  return resp.status === 204 ? (undefined as T) : resp.json()
}

export const api = {
  register: (email: string, password: string) => request<{ message: string }>('POST', '/api/auth/register', { email, password }),
  registrationInfo: () => request<RegistrationInfo>('GET', '/api/auth/registration-info'),
  resendVerification: (email: string) => request<{ message: string }>('POST', '/api/auth/resend-verification', { email }),
  verifyEmail: (token: string) => request<{ message: string }>('POST', '/api/auth/verify-email', { token }),
  async login(login: string, password: string) {
    const r = await request<{ access_token: string }>('POST', '/api/auth/login', { login, password })
    setToken(r.access_token)
  },
  companies: () => request<Company[]>('GET', '/api/companies'),
  createCompany: (name: string) => request<Company>('POST', '/api/companies', { name }),
  deleteCompany: (id: string) => request<void>('DELETE', `/api/companies/${id}`),
  company: (id: string) => request<Company>('GET', `/api/companies/${id}`),
  balance: (id: string) => request<AccountBalance>('GET', `/api/companies/${id}/balance`),
  setInitialBalance: (id: string, body: { date: string; amount: string }) => request<AccountBalance>('PUT', `/api/companies/${id}/balance/initial`, body),
  addPayment: (id: string, body: PaymentInput, key: string) => request<Operation>('POST', `/api/companies/${id}/operations`, body, { 'Idempotency-Key': key }),
  importStatement: (file: File) => { const f = new FormData(); f.append('file', file); return request<ImportResult[]>('POST', '/api/companies/import', f) },
  uploadStatement: (id: string, file: File) => { const f = new FormData(); f.append('file', file); return request<ImportResult[]>('POST', `/api/companies/${id}/statements`, f) },
  dashboard: (id: string) => request<Dashboard>('GET', `/api/companies/${id}/dashboard`),
  forecast: (id: string, horizon: number) => request<Forecast>('GET', `/api/companies/${id}/forecast?horizon=${horizon}`),
  patchCompany: (id: string, body: Partial<{ name: string; industry: string; tax_regime: string; min_balance: string }>) => request<Company>('PATCH', `/api/companies/${id}`, body),
  events: (id: string) => request<EventRow[]>('GET', `/api/companies/${id}/events`),
  // Idempotency-Key создаётся один раз на открытие формы: двойной клик не создаст два события.
  addEvent: (id: string, body: object, idemKey: string) => request<EventRow>('POST', `/api/companies/${id}/events`, body, { 'Idempotency-Key': idemKey }),
  patchEvent: (id: string, eventId: string, body: { event_date?: string; status?: 'expected' | 'cancelled' }) => request<EventRow>('PATCH', `/api/companies/${id}/events/${eventId}`, body),
  planFactDaily: (id: string) => request<DailyPlanFact>('GET', `/api/companies/${id}/plan-fact/daily`),
  preview: (id: string, body: object) => request<Forecast>('POST', `/api/companies/${id}/forecast/preview`, body),
  deleteEvent: (id: string, eventId: string) => request<void>('DELETE', `/api/companies/${id}/events/${eventId}`),
  scenario: (id: string, body: object) => request<ScenarioResult>('POST', `/api/companies/${id}/scenarios`, body),
  searchOperations: (id: string, query: string, category: string, offset = 0, limit = 50) =>
    request<Operation[]>('POST', `/api/companies/${id}/operations/search`, { query, category: category || null, offset, limit }),
  operations: (id: string, offset = 0, category = '') => request<Operation[]>('GET', `/api/companies/${id}/operations?limit=100&offset=${offset}${category ? `&category=${category}` : ''}`),
  categories: () => request<{ code: string; label: string }[]>('GET', '/meta/categories'),
  patchCategory: (opId: string, category: string, applyToCounterparty: boolean) => request<Operation[]>('PATCH', `/api/operations/${opId}/category`, { category, apply_to_counterparty: applyToCounterparty }),
  planFact: (id: string) => request<PlanFactRow[]>('GET', `/api/companies/${id}/plan-fact`),
  sync1c: (id: string) => request<{ created: number; updated: number; closed: number }>('POST', `/api/companies/${id}/sync/1c`),
  syncFns: (id: string) => request<{ inn: string; status: string; has_tax_debt: boolean; risky: boolean }[]>('POST', `/api/companies/${id}/sync/fns`),
  // Вложения: чек (один) и сопутствующие файлы. Содержимое не уходит в LLM — ассистент его не видит.
  attachments: (opId: string) => request<Attachment[]>('GET', `/api/operations/${opId}/attachments`),
  uploadAttachments: (opId: string, kind: 'receipt' | 'related', files: File[]) => {
    const f = new FormData()
    f.append('kind', kind)
    files.forEach((file) => f.append('files', file))
    return request<Attachment[]>('POST', `/api/operations/${opId}/attachments`, f)
  },
  deleteAttachment: (attId: string) => request<void>('DELETE', `/api/attachments/${attId}`),
  ask: (id: string, question: string) => request<{ answer: string; generated_by: string }>('POST', `/api/companies/${id}/assistant/ask`, { question }),
}

/** Файл вложения забираем с токеном: обычная ссылка не передала бы заголовок Authorization. */
async function attachmentBlob(att: Attachment, inline: boolean): Promise<Blob> {
  const resp = await fetch(`/api/attachments/${att.id}/file${inline ? '?inline=true' : ''}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (resp.status === 401) logout()
  if (!resp.ok) throw new ApiError(resp.status, 'Не удалось открыть файл')
  return resp.blob()
}

/** Ссылка для просмотра внутри приложения. Тип берём из белого списка сервера: открываем только PDF и картинки. */
export async function previewUrl(att: Attachment): Promise<string> {
  if (!att.previewable) throw new ApiError(415, 'Этот файл можно только скачать')
  const blob = await attachmentBlob(att, true)
  return URL.createObjectURL(new Blob([blob], { type: att.content_type }))
}

export async function downloadAttachment(att: Attachment): Promise<void> {
  const url = URL.createObjectURL(await attachmentBlob(att, false))
  const a = document.createElement('a')
  a.href = url
  a.download = att.filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 30_000)
}
