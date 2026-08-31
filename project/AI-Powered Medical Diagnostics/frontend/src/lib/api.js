const STORAGE_KEY = 'medical.diagnostics.frontend.settings'

const DEFAULTS = {
  apiUrl: import.meta.env.VITE_API_URL || '/api',
  userId: 'u1001',
  conversationId: '',
  authToken: import.meta.env.VITE_AUTH_TOKEN || '',
  tenantId: import.meta.env.VITE_TENANT_ID || 'hospital_a',
  keycloakUrl: import.meta.env.VITE_KEYCLOAK_URL || 'http://localhost:8080',
  keycloakRealm: import.meta.env.VITE_KEYCLOAK_REALM || 'medical',
  keycloakClientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID || 'medical-api',
}

export function createInitialSettings() {
  const saved = readSettings()
  return {
    apiUrl: saved.apiUrl || DEFAULTS.apiUrl,
    userId: saved.userId || DEFAULTS.userId,
    conversationId: saved.conversationId || DEFAULTS.conversationId,
    authToken: saved.authToken ?? DEFAULTS.authToken,
    tenantId: saved.tenantId || DEFAULTS.tenantId,
    keycloakUrl: saved.keycloakUrl || DEFAULTS.keycloakUrl,
    keycloakRealm: saved.keycloakRealm || DEFAULTS.keycloakRealm,
    keycloakClientId: saved.keycloakClientId || DEFAULTS.keycloakClientId,
    keycloakUsername: saved.keycloakUsername || 'doctor',
    keycloakPassword: saved.keycloakPassword || 'doctor123',
  }
}

export function hasAuthToken(settings) {
  return Boolean((settings.authToken || '').trim())
}

export function formatApiError(error) {
  const message = error?.message || String(error)
  if (message.includes('401')) {
    return (
      '需要登录：后端已启用 AUTH_ENABLED。' +
      '请在左侧点击「获取 JWT」（默认 doctor / doctor123），或粘贴 Bearer Token。' +
      '若仅本地调试，可将 .env 中 AUTH_ENABLED 设为 false 后重启后端。'
    )
  }
  if (message.includes('403') && message.includes('user_id')) {
    return (
      'user_id 与 Token 身份不一致。' +
      'JWT 登录后用户 ID 应来自 Token（非 u1001）。' +
      '请清空 Bearer Token 后重新点击「获取 JWT」，或刷新页面再试。'
    )
  }
  if (
    message.includes('Failed to fetch') ||
    message.includes('NetworkError') ||
    message.includes('ECONNREFUSED')
  ) {
    return (
      '无法连接 Keycloak（默认 http://localhost:8080）。' +
      '请先运行 ./scripts/keycloak_up.sh；' +
      '若不需要鉴权，将 .env 中 AUTH_ENABLED=false 后重启 ./scripts/start.sh。'
    )
  }
  return message
}

export function isJwtToken(token) {
  return (token || '').trim().split('.').length === 3
}

export function parseJwtPayload(token) {
  try {
    const body = token.trim().split('.')[1]
    if (!body) return null
    const base64 = body.replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '=')
    return JSON.parse(atob(padded))
  } catch {
    return null
  }
}

/** JWT 登录后把 sub / tenant_id 写入 settings，避免与 AUTH_BIND_USER_ID 冲突 */
export function syncSettingsFromToken(settings) {
  const token = (settings.authToken || '').trim()
  if (!isJwtToken(token)) return false
  const payload = parseJwtPayload(token)
  if (!payload) return false

  if (payload.sub) {
    settings.userId = String(payload.sub)
  }
  const tenant = payload.tenant_id
  if (Array.isArray(tenant) && tenant[0]) {
    settings.tenantId = String(tenant[0])
  } else if (typeof tenant === 'string' && tenant.trim()) {
    settings.tenantId = tenant.trim()
  }
  saveSettings(settings)
  return true
}

export async function ensureAuthToken(settings) {
  if (hasAuthToken(settings)) {
    syncSettingsFromToken(settings)
    return settings.authToken.trim()
  }
  const user = (settings.keycloakUsername || '').trim()
  const password = (settings.keycloakPassword || '').trim()
  if (!user || !password) {
    throw new Error(formatApiError({ message: '401 Unauthorized' }))
  }
  const token = await fetchKeycloakToken(settings)
  settings.authToken = token
  syncSettingsFromToken(settings)
  return token
}

export function saveSettings(settings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
}

export function apiBase(settings) {
  return normalizeBaseUrl(settings.apiUrl)
}

export function authHeaders(settings, { admin = false } = {}) {
  const headers = {}
  const token = (settings.authToken || '').trim()
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  if (admin && (settings.tenantId || '').trim()) {
    headers['X-Tenant-ID'] = settings.tenantId.trim()
  }
  return headers
}

export async function requestHealth(settings) {
  return requestJson(settings, '/health')
}

export async function requestMonitor(settings) {
  return requestJson(settings, '/monitor')
}

export async function requestKnowledgeStats(settings) {
  const data = await requestJson(settings, '/knowledge/stats')
  return {
    ...data,
    total_chunks: data.total_chunks ?? data.chunk_count ?? data.total,
  }
}

export async function requestSearch(settings, query, topK = 5) {
  const params = new URLSearchParams({ query, top_k: String(topK) })
  return requestJson(settings, `/search?${params}`, { method: 'POST' })
}

export async function requestChat(settings, message) {
  syncSettingsFromToken(settings)
  const payload = {
    message,
    user_id: settings.userId || 'anonymous',
    conv_id: settings.conversationId || undefined,
  }
  const raw = await requestJson(settings, '/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(settings) },
    body: JSON.stringify(payload),
  })
  return normalizeChatResponse(raw)
}

export async function addKnowledge(settings, documents) {
  return requestJson(settings, '/knowledge/add', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(settings, { admin: true }),
    },
    body: JSON.stringify({ documents }),
  })
}

export async function importKnowledgeDirectory(
  settings,
  directory = 'data/medical_knowledge',
) {
  return requestJson(settings, '/knowledge/import', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(settings, { admin: true }),
    },
    body: JSON.stringify({ directory, recursive: true }),
  })
}

export async function fetchKeycloakToken(settings) {
  const base = normalizeBaseUrl(settings.keycloakUrl)
  const realm = settings.keycloakRealm || 'medical'
  const url = `${base}/realms/${realm}/protocol/openid-connect/token`
  const body = new URLSearchParams({
    client_id: settings.keycloakClientId || 'medical-api',
    username: settings.keycloakUsername || 'doctor',
    password: settings.keycloakPassword || '',
    grant_type: 'password',
  })
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
  const text = await response.text()
  let data = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = { raw: text }
  }
  if (!response.ok) {
    throw new Error(`${response.status}: ${data?.error_description || data?.error || text}`)
  }
  return data.access_token
}

function normalizeChatResponse(raw) {
  return {
    conversationId: raw.conv_id || raw.conversation_id || '',
    response: raw.response || '',
    intent: raw.intent || 'other',
    agentType: raw.agent_type || '',
    escalated: Boolean(raw.escalated),
    emergency: Boolean(raw.emergency),
    blocked: Boolean(raw.blocked),
    hitlRequired: Boolean(raw.hitl_required),
    safetyPassed: raw.safety_passed ?? true,
    disclaimer: raw.disclaimer || '',
    sources: Array.isArray(raw.sources) ? raw.sources : [],
    latencyMs: Number(raw.latency_ms ?? 0),
    knowledgeUsed: Boolean(raw.knowledge_used),
    requestId: raw.request_id || '',
    raw,
  }
}

async function requestJson(settings, path, options = {}) {
  const url = `${apiBase(settings)}${path}`
  const headers = {
    ...authHeaders(settings),
    ...(options.headers || {}),
  }
  const response = await fetch(url, { ...options, headers })
  const text = await response.text()
  let data = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }
  if (!response.ok) {
    const detail =
      typeof data === 'object' && data?.detail
        ? JSON.stringify(data.detail)
        : typeof data === 'string'
          ? data
          : JSON.stringify(data)
    throw new Error(`${response.status} ${response.statusText}: ${detail}`)
  }
  return data
}

function normalizeBaseUrl(value) {
  return String(value || '').replace(/\/+$/, '')
}

function readSettings() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
  } catch {
    return {}
  }
}
