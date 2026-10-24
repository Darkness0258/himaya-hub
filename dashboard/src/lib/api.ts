import type {
  Category,
  Device,
  EnrollInfo,
  HubEvent,
  HubSettings,
  RemoteAction,
  Rules,
  RulesPatch,
  Snapshot,
  Stats,
} from './types'

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

const KEY_NAME = 'himaya.key'
let apiKey = ''
let onUnauthorized: (() => void) | null = null

export function loadStoredKey(): string {
  try {
    return localStorage.getItem(KEY_NAME) || sessionStorage.getItem(KEY_NAME) || ''
  } catch {
    return ''
  }
}

export function storeKey(key: string, remember: boolean): void {
  apiKey = key
  try {
    localStorage.removeItem(KEY_NAME)
    sessionStorage.removeItem(KEY_NAME)
    if (key) (remember ? localStorage : sessionStorage).setItem(KEY_NAME, key)
  } catch {
    /* storage can be blocked; the key then only lives in memory for this tab */
  }
}

export function getApiKey(): string {
  return apiKey
}

export function isKeyRemembered(): boolean {
  try {
    return Boolean(localStorage.getItem(KEY_NAME))
  } catch {
    return false
  }
}

/** Load the remembered key into memory (call once at start-up). */
export function restoreKey(): string {
  apiKey = loadStoredKey()
  return apiKey
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler
}

/** Turn FastAPI's `{detail: ...}` (string or validation-error list) into one readable sentence. */
export function readableError(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string; loc?: unknown[] }
    const msg = (first.msg ?? '').replace(/^Value error, /, '')
    const field = Array.isArray(first.loc) ? String(first.loc[first.loc.length - 1] ?? '') : ''
    return field && field !== 'body' ? `${field.replace(/_/g, ' ')}: ${msg}` : msg || 'That value is not valid.'
  }
  if (status === 429) return 'Too many attempts. Wait a minute and try again.'
  if (status >= 500) return 'The hub hit a problem. Check its console window.'
  return `The hub refused that request (${status}).`
}

async function request<T>(path: string, init: { method?: string; json?: unknown; keyOverride?: string } = {}): Promise<T> {
  const headers: Record<string, string> = { 'X-API-Key': init.keyOverride ?? apiKey }
  let body: string | undefined
  if (init.json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(init.json)
  }
  let response: Response
  try {
    response = await fetch(path, { method: init.method ?? 'GET', headers, body })
  } catch {
    throw new ApiError("Can't reach the hub. Is it running and on the same network?", 0)
  }
  if (!response.ok) {
    let parsed: unknown = null
    try {
      parsed = await response.json()
    } catch {
      /* not JSON */
    }
    if (response.status === 401 && init.keyOverride === undefined) onUnauthorized?.()
    throw new ApiError(readableError(parsed, response.status), response.status)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

const query = (params: Record<string, string | number | undefined>): string => {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== '') search.set(key, String(value))
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const api = {
  /** Check a key without touching the stored one (used by the sign-in form). */
  checkKey: (key: string) => request<{ role: string; version: string }>('/api/me', { keyOverride: key }),
  devices: () => request<Device[]>('/devices'),
  events: (params: { limit?: number; before_id?: number; device_id?: string; type?: string } = {}) =>
    request<HubEvent[]>(`/events${query(params)}`),
  stats: () => request<Stats>('/api/stats'),
  categories: () => request<Category[]>('/api/categories'),
  settings: () => request<HubSettings>('/api/settings'),
  snapshots: (params: { device_id?: string; limit?: number; before_id?: number } = {}) =>
    request<Snapshot[]>(`/snapshots${query(params)}`),
  deleteSnapshot: (id: number) => request<{ status: string }>(`/snapshots/${id}`, { method: 'DELETE' }),
  rules: (id: string) => request<Rules>(`/rules/${id}`),
  saveRules: (id: string, patch: RulesPatch) => request<Rules>(`/rules/${id}`, { method: 'POST', json: patch }),
  action: (id: string, action: RemoteAction, payload: Record<string, unknown> = {}) =>
    request<{ status: string; device: Device }>(`/admin/${id}/action`, { method: 'POST', json: { action, payload } }),
  renameDevice: (id: string, patch: { name?: string; owner_type?: 'child' | 'adult' }) =>
    request<Device>(`/devices/${id}`, { method: 'PATCH', json: patch }),
  deleteDevice: (id: string) => request<{ status: string }>(`/devices/${id}`, { method: 'DELETE' }),
  enrollInfo: () => request<EnrollInfo>('/enroll/info'),
  regeneratePin: () => request<{ pin: string; pin_expires_in: number }>('/enroll/pin/regenerate', { method: 'POST' }),
  setPublicUrl: (url: string) => request<{ public_url: string | null }>('/enroll/public-url', { method: 'POST', json: { url } }),
  rotateAdminKey: () => request<{ admin_key: string }>('/api/admin-key/rotate', { method: 'POST' }),
}
