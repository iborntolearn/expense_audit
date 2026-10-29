// Typed client for the Veriflow REST API (integration/app.py + routes/*).
// All requests go through Vite's /api proxy (see vite.config.ts) to the
// uvicorn service - see memory: it currently runs on port 8001, not 8000.

const TOKEN_KEY = 'expense_audit_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

async function request<T>(
  method: string,
  path: string,
  { json, params }: { json?: unknown; params?: Record<string, string | number | boolean | undefined> } = {},
): Promise<T> {
  const url = new URL(`/api${path}`, window.location.origin)
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== '') url.searchParams.set(k, String(v))
    }
  }
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (json !== undefined) headers['Content-Type'] = 'application/json'

  const res = await fetch(url.toString(), {
    method,
    headers,
    body: json !== undefined ? JSON.stringify(json) : undefined,
  })

  if (res.status === 401) {
    setToken(null)
    onUnauthorized?.()
    throw new ApiError(401, 'session expired - please log in again')
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? JSON.stringify(body)
    } catch {
      // ignore - use statusText
    }
    throw new ApiError(res.status, typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  const contentType = res.headers.get('content-type') ?? ''
  if (contentType.includes('application/json')) return res.json()
  return res as unknown as T
}

async function uploadForm<T>(path: string, form: FormData): Promise<T> {
  const url = new URL(`/api${path}`, window.location.origin)
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  // No Content-Type here - the browser sets the multipart boundary itself.
  const res = await fetch(url.toString(), { method: 'POST', headers, body: form })
  if (res.status === 401) {
    setToken(null)
    onUnauthorized?.()
    throw new ApiError(401, 'session expired - please log in again')
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? JSON.stringify(body)
    } catch {
      // ignore - use statusText
    }
    throw new ApiError(res.status, typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res.json()
}

const get = <T>(path: string, params?: Record<string, string | number | boolean | undefined>) =>
  request<T>('GET', path, { params })
const post = <T>(path: string, json?: unknown, params?: Record<string, string | number | boolean | undefined>) =>
  request<T>('POST', path, { json, params })
const put = <T>(path: string, json?: unknown, params?: Record<string, string | number | boolean | undefined>) =>
  request<T>('PUT', path, { json, params })
const patch = <T>(path: string, json?: unknown) => request<T>('PATCH', path, { json })
const del = <T>(path: string) => request<T>('DELETE', path)

// ---------------------------------------------------------------- types ---
export type Role = 'admin' | 'user' | 'auditor'

export interface CurrentUser {
  username: string
  display_name: string
  role: Role
  // null = global/unscoped (only meaningful for role 'admin' - a super-admin
  // spanning every OE); every other role always carries a real OE code.
  oe_code: string | null
}

export interface LoginResponse {
  access_token: string
  token_type: string
  username: string
  display_name: string
  role: Role
  oe_code: string | null
}

export interface ReportRow {
  submission_id: string
  employee_id: string
  submitted_at: string
  total: number
  currency: string
  risk_score: number
  risk_band: 'LOW' | 'PENDING' | 'HIGH'
  risk_reason: string
  approver: string
  violations: number
  flags: number
  insight_count: number
  status: 'APPROVED' | 'REJECTED' | 'SUBMITTED'
  routing_decision: string
}

export interface ReportDetail {
  submission: Record<string, any>
  extracted_lines: Array<Record<string, any>>
  verification: Record<string, any>
  policy: Array<{ rule_id: string; passed: boolean }>
  risk: Record<string, any>
  receipts: Array<{ line_id: string; receipt_url: string }>
}

export interface CaseStatus {
  submission_id: string
  status: string
  recovered_amount: number | null
  updated_by?: string
  updated_at?: string
}

export interface EmailTemplateRaw {
  name: string
  subject: string
  body: string
}

export interface DashboardData {
  kpis: Record<string, number>
  routing: Record<string, number>
  spend_by_category: Record<string, number>
  spend_by_oe: Record<string, number>
  spend_by_currency: Record<string, number>
  top_rules: Array<{ rule_id: string; violations: number }>
  exception_reasons: Record<string, number>
  risk_histogram: Record<string, number>
  trend: Array<{ date: string; submissions: number; automation_rate: number }>
  recent_decisions: Array<Record<string, any>>
  reviewer_outcomes: Record<string, number>
}

export interface UserAnalyticsData {
  employee_id: string
  kpis: {
    te_spend: number
    rejected_high_risk_spend: number
    abi_score: number
    auto_approved: number
    total_reports: number
  }
  spend_by_type: Record<string, { spend: number; lines: number }>
  high_risk_spend_by_type: Record<string, number>
  behavioral_trends: Array<{ trend: string; value: number }>
  spend_by_geo: Record<string, number>
  company_abi: number[]
  my_abi: number
}

export interface AssistantAnswer {
  text: string
  metric: [string, string] | null
  chart: { label: string; value: string; data: Array<Record<string, any>> } | null
  table: Array<Record<string, any>> | null
  suggestions: string[]
}

export interface AssistantHistoryTurn {
  role: 'user' | 'assistant'
  content: string
}

export interface CompliancePacks {
  sox_icfr: {
    total_submissions: number
    auto_approved_pct: number
    auto_rejected_pct: number
    human_review_pct: number
    violations_by_rule: Array<{ rule_id: string; violation_count: number }>
  }
  fcpa_sanctions: {
    flagged: Array<{
      submission_id: string
      employee_id: string
      submitted_at: string
      routing_decision: string
      compliance_flags: string[]
      merchant_flags: string[]
    }>
  }
  recoverable_funds: {
    cases_tracked: number
    claw_back_pending: number
    resolved: number
    total_recovered: number
    cases: CaseStatus[]
  }
}

export interface AdminUser {
  username: string
  display_name: string
  role: Role
  oe_code: string | null
}

export interface WatchlistEntry {
  name: string
  type: string
  reason: string
}

export interface MerchantRegistryRow {
  merchant_key: string
  display_name: string
  status: 'clear' | 'watch' | 'blocked'
  risk_tier: 'low' | 'medium' | 'high'
  source: 'bootstrap_yaml' | 'auto' | 'admin_override'
  blocklist_type: string | null
  reason: string | null
  first_seen_at: string
  last_seen_at: string
  submission_count: number
  updated_by: string | null
  updated_at: string
}

export interface EnvironmentInfo {
  mode_requested: string
  live_mode_active: boolean
  storage_backend: string
  engine: string
  vision_provider: string
  embedding_dim: number
  azure_deployment?: string
  azure_api_version?: string
  azure_endpoint?: string
  azure_openai_key_set?: boolean
  vision_model?: string
  anthropic_key_set?: boolean
  sqlite_path: string
  checkpoint_path: string
  live_mode_blocked_reason: string | null
}

export interface ReportLinePayload {
  line_id: string
  category: string
  entered_amount: number
  receipt_url: string
}

export interface SubmissionEvent {
  event_type: string
  submission_id: string
  source_system: string
  source_system_ref: string
  oe_code: string
  employee_id: string
  cost_center: string | null
  currency: string
  submitted_at: string
  report_lines: ReportLinePayload[]
}

export interface IngestResult {
  submission_id: string
  accepted: boolean
  reason: string
  routing_decision: string | null
}

export interface ItemizedEntry {
  description?: string | null
  vendor?: string | null
  date?: string | null
  amount: number | null
  tax?: number | null
  currency?: string | null
  category: string
  confidence?: number
}

// ---------------------------------------------------------------- auth ---
export const authApi = {
  login: (username: string, password: string) =>
    post<LoginResponse>('/auth/login', { username, password }),
  logout: () => post('/auth/logout'),
  me: () => get<CurrentUser>('/auth/me'),
}

// ------------------------------------------------------------- reports ---
export interface InsightEntry {
  type: string
  label: string
  detail: string
}

export interface PipelineStep {
  node: string
  ok: boolean
  attempts: number
  latency_ms: number
  input_summary?: string
  output_summary?: string
  error_message?: string
  logged_at?: string
}

export const reportsApi = {
  list: (filters?: {
    employee_id?: string
    submission_id?: string
    status_filter?: string
    risk_band?: string
    pending_only?: boolean
    oe_code?: string
  }) => get<ReportRow[]>('/reports', filters),
  detail: (sid: string) => get<ReportDetail>(`/reports/${encodeURIComponent(sid)}`),
  decide: (sid: string, reviewer_id: string, approved: boolean, notes?: string) =>
    post(`/reports/${encodeURIComponent(sid)}/decision`, { reviewer_id, approved, notes }),
  insights: (sid: string) => get<InsightEntry[]>(`/reports/${encodeURIComponent(sid)}/insights`),
  pipelineLog: (sid: string) => get<PipelineStep[]>(`/reports/${encodeURIComponent(sid)}/pipeline-log`),
  receiptUrl: (sid: string, lineId: string) =>
    `/api/reports/${encodeURIComponent(sid)}/receipt/${encodeURIComponent(lineId)}`,
}

export const caseStatusApi = {
  get: (sid: string) => get<CaseStatus>(`/case-status/${encodeURIComponent(sid)}`),
  update: (sid: string, status: string, recovered_amount: number | null, updated_by: string) =>
    put<CaseStatus>(`/case-status/${encodeURIComponent(sid)}`, { status, recovered_amount, updated_by }),
}

export const emailTemplatesApi = {
  list: () => get<string[]>('/email-templates'),
  render: (template_name: string, submission_id: string, reason: string) =>
    post<{ subject: string; body: string }>('/email-templates/render', { template_name, submission_id, reason }),
  listRaw: () => get<EmailTemplateRaw[]>('/email-templates/admin/raw'),
  save: (name: string, subject: string, body: string) =>
    put(`/email-templates/admin/raw/${encodeURIComponent(name)}`, { subject, body }),
}

export const analyticsApi = {
  dashboard: (oe_code?: string) => get<DashboardData>('/dashboard', { oe_code }),
  userAnalytics: (employee_id: string, period_days?: number, oe_code?: string) =>
    get<UserAnalyticsData>('/user-analytics', { employee_id, period_days, oe_code }),
}

export const assistantApi = {
  examples: () => get<string[]>('/assistant/examples'),
  ask: (question: string, oe_code?: string, history?: AssistantHistoryTurn[]) =>
    post<AssistantAnswer>('/assistant/ask', { question, history: history ?? [] }, { oe_code }),
}

export const reportsExportApi = {
  pipelineLogs: (limit = 5000, oe_code?: string) =>
    get<Array<Record<string, any>>>('/pipeline-logs', { limit, oe_code }),
  compliancePacks: (oe_code?: string) => get<CompliancePacks>('/compliance-packs', { oe_code }),
  accuracyLatency: () =>
    get<{ source: string; metrics: Array<Record<string, any>>; markdown_available: boolean }>(
      '/reports-export/accuracy-latency',
    ),
  downloadUrl: (fmt: 'json' | 'markdown') => `/api/reports-export/accuracy-latency/download?fmt=${fmt}`,
}

// --------------------------------------------------------- admin: users ---
export const adminUsersApi = {
  list: () => get<AdminUser[]>('/admin/users'),
  add: (username: string, display_name: string, role: Role, password: string, oe_code: string | null = null) =>
    post('/admin/users', { username, display_name, role, password, oe_code }),
  resetPassword: (username: string, new_password: string) =>
    put(`/admin/users/${encodeURIComponent(username)}/password`, { new_password }),
  setRole: (username: string, role: Role) =>
    put(`/admin/users/${encodeURIComponent(username)}/role`, { role }),
  setOe: (username: string, oe_code: string | null) =>
    put(`/admin/users/${encodeURIComponent(username)}/oe`, { oe_code }),
  remove: (username: string) => del(`/admin/users/${encodeURIComponent(username)}`),
}

export const adminWatchlistApi = {
  list: () => get<WatchlistEntry[]>('/admin/watchlist'),
  add: (name: string, entry_type: string, reason: string) =>
    post('/admin/watchlist', { name, entry_type, reason }),
  remove: (name: string) => del(`/admin/watchlist/${encodeURIComponent(name)}`),
  listRegistry: (status?: string) =>
    get<MerchantRegistryRow[]>('/admin/watchlist/registry', { status_filter: status }),
  updateRegistry: (
    merchantKey: string,
    updates: { status?: string; risk_tier?: string; reason?: string },
  ) => patch(`/admin/watchlist/registry/${encodeURIComponent(merchantKey)}`, updates),
}

export const adminConfigApi = {
  // `oe` is only ever honored server-side for a global admin (oe_code=null) -
  // an OE-scoped admin always gets/saves their own OE's view regardless of
  // what's passed, so passing it unconditionally here is safe.
  getPipeline: (oe?: string) => get<Record<string, any>>('/admin/config/pipeline', { oe }),
  putPipeline: (data: Record<string, any>, oe?: string) => put('/admin/config/pipeline', data, { oe }),
  getGenerator: (oe?: string) => get<Record<string, any>>('/admin/config/generator', { oe }),
  putGenerator: (data: Record<string, any>, oe?: string) => put('/admin/config/generator', data, { oe }),
  getThresholds: (oe?: string) => get<Record<string, any>>('/admin/config/thresholds', { oe }),
  putThresholds: (data: Record<string, any>, oe?: string) => put('/admin/config/thresholds', data, { oe }),
  getPolicy: (oe?: string) => get<Record<string, any>>('/admin/config/policy', { oe }),
  putPolicy: (data: Record<string, any>, oe?: string) => put('/admin/config/policy', data, { oe }),
  getEnv: (key: string) => get<{ key: string; value: string }>(`/admin/config/env/${encodeURIComponent(key)}`),
  putEnv: (updates: Record<string, string>) => put('/admin/config/env', { updates }),
}

export const adminDangerApi = {
  summary: () => get<{ submissions: number; blob_files: number; checkpoint_present: boolean }>(
    '/admin/danger/summary',
  ),
  purge: () => post<Record<string, any>>('/admin/danger/purge', { confirm: true }),
}

// --------------------------------------------------------- admin: environment ---
export const adminEnvironmentApi = {
  get: () => get<EnvironmentInfo>('/admin/environment'),
  reload: () => post<{ ok: boolean; note: string }>('/admin/reload'),
}

// --------------------------------------------------------- admin: connectors ---
export interface ConnectorRoleStatus {
  provider: string
  options: string[]
  configured: boolean
}

export interface ConnectorsStatus {
  submission_source: ConnectorRoleStatus
  employee_directory: ConnectorRoleStatus
  finance_master: ConnectorRoleStatus
}

export interface ConnectorsConfigInput {
  submission_source: string
  employee_directory: string
  finance_master: string
}

export interface ConnectorTestResult {
  provider: string
  ok: boolean
  detail: string
}

export const connectorsApi = {
  get: () => get<ConnectorsStatus>('/admin/connectors'),
  putConfig: (config: ConnectorsConfigInput) => put<{ ok: boolean; note: string }>('/admin/connectors', config),
  test: (role: string) => post<ConnectorTestResult>(`/admin/connectors/${encodeURIComponent(role)}/test`),
}

// --------------------------------------------------------- admin: devtools ---
export const adminDevtoolsApi = {
  uploadReceipt: (file: File, submissionId: string, mode: 'manual' | 'auto') => {
    const form = new FormData()
    form.append('submission_id', submissionId)
    form.append('mode', mode)
    form.append('file', file)
    return uploadForm<{ key: string; receipt_url: string }>('/admin/receipts/upload', form)
  },
  simulateAuthenticity: (key: string) => post<{ ok: boolean }>('/admin/receipts/simulate-authenticity', { key }),
  autoDetect: (key: string, currency: string) =>
    post<{ items: ItemizedEntry[] }>('/admin/receipts/auto-detect', { key, currency }),
  saveItemization: (key: string, items: ItemizedEntry[]) =>
    post<{ ok: boolean }>('/admin/receipts/save-itemization', { key, items }),
  generateSyntheticEvents: (sample_size: number) =>
    post<{ seed: number; events: SubmissionEvent[] }>('/admin/generate-synthetic-events', { sample_size }),
  ingestEvent: (event: SubmissionEvent) => post<IngestResult>('/admin/ingest-event', event),
}

// ------------------------------------------------------------ webhooks ---
export const webhooksApi = {
  submissionCreated: (event: SubmissionEvent) => post<IngestResult>('/webhooks/submission-created', event),
}
