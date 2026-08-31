<template>
  <main class="app-shell medical-mode">
    <aside class="sidebar">
      <section class="brand">
        <div class="brand-mark">MD</div>
        <div>
          <h1>AI-Powered Medical Diagnostics</h1>
          <p>医疗导诊 · 报告解释</p>
        </div>
      </section>

      <div class="disclaimer-card">
        <strong>非诊断系统</strong>
        <p>仅供参考，不能替代医生诊断与处方。急症请拨打 120 或前往急诊。</p>
      </div>

      <div v-if="authRequired && !hasToken" class="auth-banner">
        <strong>需要登录</strong>
        <p>后端已启用鉴权。请先点击「获取 JWT」，或填写 Bearer Token。</p>
        <button type="button" class="secondary" :disabled="busy" @click="loginKeycloak">
          立即获取 JWT
        </button>
      </div>

      <section class="panel">
        <div class="panel-heading">
          <h2>连接</h2>
          <span class="pill">8010</span>
        </div>
        <label>
          <span>API 地址</span>
          <input v-model="settings.apiUrl" @change="persist" placeholder="/api" />
        </label>
        <label>
          <span>用户 ID</span>
          <input v-model="settings.userId" @change="persist" placeholder="JWT 登录后自动同步 sub" />
          <small v-if="hasToken" class="field-hint">JWT 模式下由 Token 的 sub 决定，请勿手动改为 u1001</small>
        </label>
        <label>
          <span>会话 ID</span>
          <input v-model="settings.conversationId" @change="persist" placeholder="自动生成" />
        </label>
        <label>
          <span>Bearer Token</span>
          <textarea
            v-model="settings.authToken"
            @change="onAuthTokenChange"
            rows="2"
            placeholder="AUTH_ENABLED 时必填（API Key 或 JWT）"
          />
        </label>
        <label>
          <span>租户 ID（管理接口）</span>
          <input v-model="settings.tenantId" @change="persist" placeholder="hospital_a" />
        </label>
        <div class="actions">
          <button type="button" @click="checkHealth">健康检查</button>
          <button type="button" @click="loadStats">刷新状态</button>
          <button type="button" class="secondary" @click="newConversation">新会话</button>
        </div>
      </section>

      <section class="panel">
        <div class="panel-heading">
          <h2>Keycloak 取 Token</h2>
          <span class="pill soft">OIDC</span>
        </div>
        <label>
          <span>Keycloak URL</span>
          <input v-model="settings.keycloakUrl" @change="persist" placeholder="http://localhost:8080" />
        </label>
        <label>
          <span>用户名 / 密码</span>
          <div class="inline-form">
            <input v-model="settings.keycloakUsername" @change="persist" placeholder="doctor" />
            <input
              v-model="settings.keycloakPassword"
              @change="persist"
              type="password"
              placeholder="doctor123"
            />
          </div>
        </label>
        <button type="button" class="secondary" :disabled="busy" @click="loginKeycloak">
          获取 JWT
        </button>
      </section>

      <section class="panel status-panel">
        <div class="panel-heading">
          <h2>状态</h2>
          <span :class="['status-dot', healthOk ? 'online' : 'offline']" />
        </div>
        <dl>
          <div>
            <dt>健康</dt>
            <dd :class="healthOk ? 'ok' : 'muted'">{{ healthLabel }}</dd>
          </div>
          <div>
            <dt>知识片段</dt>
            <dd>{{ knowledgeCount }}</dd>
          </div>
          <div>
            <dt>Release</dt>
            <dd>{{ releaseId }}</dd>
          </div>
        </dl>
        <pre v-if="statusText">{{ statusText }}</pre>
      </section>
    </aside>

    <section class="workspace">
      <header class="workspace-header">
        <div>
          <span class="eyebrow">Medical Diagnostics</span>
          <h2>导诊 / 报告解释</h2>
          <p>{{ apiBaseUrl }} · 后端端口 8010</p>
        </div>
        <div class="header-actions">
          <a :href="docsUrl" target="_blank" rel="noreferrer">API 文档</a>
        </div>
      </header>

      <section class="chat-panel">
        <div ref="messageList" class="messages">
          <article
            v-for="item in messages"
            :key="item.id"
            :class="['message', item.role, { emergency: item.emergency, blocked: item.blocked }]"
          >
            <div class="message-meta">
              <span>{{ item.role === 'user' ? '用户' : '助手' }}</span>
              <small v-if="item.meta">{{ item.meta }}</small>
            </div>
            <p class="message-body">{{ item.content }}</p>
            <ul v-if="item.sources?.length" class="source-list">
              <li v-for="(src, idx) in item.sources" :key="idx">
                <strong>[{{ src.doc_type || 'ref' }}] {{ src.title }}</strong>
                <span v-if="src.score != null"> · {{ src.score }}</span>
                <p>{{ src.content }}</p>
              </li>
            </ul>
          </article>
          <div v-if="messages.length === 0" class="empty-state">
            <h3>描述症状或检查指标</h3>
            <p>例如：ALT 52 偏高是什么意思？肚子胀应该挂什么科？</p>
          </div>
        </div>

        <form class="composer" @submit.prevent="sendMessage">
          <textarea
            v-model="draft"
            rows="3"
            placeholder="输入症状或报告指标，例如：体检 ALT 52 偏高，应该挂什么科？"
          />
          <button :disabled="busy || !draft.trim()">{{ busy ? '发送中…' : '发送' }}</button>
        </form>
      </section>

      <section class="tools-grid">
        <article class="tool-panel">
          <div class="panel-heading">
            <h2>知识库检索</h2>
            <span class="pill soft">RAG</span>
          </div>
          <div class="inline-form">
            <input v-model="searchQuery" placeholder="ALT 偏高 挂什么科" />
            <button type="button" :disabled="busy || !searchQuery.trim()" @click="searchKnowledge">
              检索
            </button>
          </div>
          <div class="result-list">
            <article v-for="(item, idx) in searchResults" :key="idx" class="result-item">
              <strong>{{ item.title || '未命名' }}</strong>
              <span>score {{ item.score ?? '-' }}</span>
              <p>{{ item.content }}</p>
            </article>
          </div>
        </article>

        <article class="tool-panel">
          <div class="panel-heading">
            <h2>导入知识</h2>
            <span class="pill soft">Admin</span>
          </div>
          <p class="hint">需 admin Token；写入租户见侧栏「租户 ID」。</p>
          <label>
            <span>文档类型</span>
            <select v-model="docType">
              <option value="popular_science">科普</option>
              <option value="department">科室</option>
              <option value="lab_item">检查项</option>
              <option value="hospital_flow">就诊流程</option>
            </select>
          </label>
          <label>
            <span>标题</span>
            <input v-model="docTitle" placeholder="空腹血糖说明" />
          </label>
          <label>
            <span>内容</span>
            <textarea v-model="docContent" rows="5" placeholder="输入知识库内容" />
          </label>
          <div class="actions">
            <button
              type="button"
              :disabled="busy || !docTitle.trim() || !docContent.trim()"
              @click="submitKnowledge"
            >
              添加文档
            </button>
            <button type="button" class="secondary" :disabled="busy" @click="batchImportKnowledge">
              批量导入目录
            </button>
          </div>
        </article>
      </section>
    </section>
  </main>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import {
  addKnowledge,
  apiBase,
  createInitialSettings,
  ensureAuthToken,
  fetchKeycloakToken,
  formatApiError,
  hasAuthToken,
  importKnowledgeDirectory,
  requestChat,
  requestHealth,
  requestKnowledgeStats,
  requestMonitor,
  requestSearch,
  saveSettings,
  syncSettingsFromToken,
} from './lib/api'

const settings = reactive(createInitialSettings())
const messages = ref([])
const draft = ref('')
const busy = ref(false)
const healthOk = ref(false)
const authRequired = ref(false)
const healthLabel = ref('未检查')
const statusText = ref('')
const knowledgeCount = ref('-')
const releaseId = ref('-')
const searchQuery = ref('ALT 偏高')
const searchResults = ref([])
const docTitle = ref('空腹血糖说明')
const docContent = ref('空腹血糖反映至少 8 小时未进食后的血糖水平，单次升高建议复测。')
const docType = ref('lab_item')
const messageList = ref(null)

const apiBaseUrl = computed(() => apiBase(settings))
const docsUrl = computed(() => `${apiBaseUrl.value}/docs`)
const hasToken = computed(() => hasAuthToken(settings))

watch(
  () => settings.conversationId,
  () => persist(),
)

onMounted(() => {
  syncSettingsFromToken(settings)
  checkHealth()
  loadStats()
})

function onAuthTokenChange() {
  syncSettingsFromToken(settings)
  persist()
}

function createId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

function persist() {
  saveSettings(settings)
}

function newConversation() {
  settings.conversationId = ''
  messages.value = []
  persist()
}

async function loginKeycloak() {
  busy.value = true
  try {
    settings.authToken = await fetchKeycloakToken(settings)
    syncSettingsFromToken(settings)
    persist()
    statusText.value = settings.userId
      ? `已从 Keycloak 获取 JWT（user_id=${settings.userId.slice(0, 8)}…）`
      : '已从 Keycloak 获取 JWT'
  } catch (error) {
    statusText.value = error.message
  } finally {
    busy.value = false
  }
}

async function sendMessage() {
  const content = draft.value.trim()
  if (!content) return
  messages.value.push({ id: createId(), role: 'user', content })
  draft.value = ''
  busy.value = true
  try {
    if (authRequired.value) {
      await ensureAuthToken(settings)
    }
    const response = await requestChat(settings, content)
    if (response.conversationId && !settings.conversationId) {
      settings.conversationId = response.conversationId
      persist()
    }
    const metaParts = [
      response.intent,
      response.agentType,
      response.knowledgeUsed ? 'RAG' : '',
      response.emergency ? '紧急' : '',
      response.escalated ? '升级' : '',
      response.blocked ? '已拦截' : '',
      response.safetyPassed === false ? '安全改写' : '',
      response.latencyMs ? `${response.latencyMs}ms` : '',
    ].filter(Boolean)
    messages.value.push({
      id: createId(),
      role: 'assistant',
      content: response.response,
      meta: metaParts.join(' · '),
      sources: response.sources,
      emergency: response.emergency,
      blocked: response.blocked,
    })
  } catch (error) {
    messages.value.push({
      id: createId(),
      role: 'assistant',
      content: formatApiError(error),
      meta: '请求失败',
    })
  } finally {
    busy.value = false
    await nextTick()
    messageList.value?.scrollTo({ top: messageList.value.scrollHeight, behavior: 'smooth' })
  }
}

async function checkHealth() {
  try {
    const data = await requestHealth(settings)
    healthOk.value = data.status === 'ok'
    authRequired.value = Boolean(data.auth_enabled)
    healthLabel.value = data.status || 'ok'
    statusText.value = JSON.stringify(data, null, 2)
    if (data.knowledge_chunks != null) knowledgeCount.value = data.knowledge_chunks
    if (data.release_id) releaseId.value = data.release_id
  } catch (error) {
    healthOk.value = false
    healthLabel.value = '不可用'
    statusText.value = error.message
  }
}

async function loadStats() {
  try {
    const [stats, monitor] = await Promise.allSettled([
      requestKnowledgeStats(settings),
      requestMonitor(settings),
    ])
    if (stats.status === 'rejected' && String(stats.reason?.message).includes('401')) {
      authRequired.value = true
    }
    if (monitor.status === 'rejected' && String(monitor.reason?.message).includes('401')) {
      authRequired.value = true
    }
    if (stats.status === 'fulfilled') {
      knowledgeCount.value = stats.value.total_chunks ?? stats.value.chunk_count ?? '-'
      if (stats.value.auth?.tenant_id) {
        statusText.value = JSON.stringify(stats.value, null, 2)
      }
    }
    if (monitor.status === 'fulfilled') {
      statusText.value = JSON.stringify(monitor.value, null, 2)
    } else if (stats.status === 'fulfilled') {
      statusText.value = JSON.stringify(stats.value, null, 2)
    }
  } catch (error) {
    if (String(error?.message).includes('401')) {
      authRequired.value = true
    }
    statusText.value = formatApiError(error)
  }
}

async function searchKnowledge() {
  busy.value = true
  try {
    const data = await requestSearch(settings, searchQuery.value, 5)
    searchResults.value = data.results || []
    statusText.value = JSON.stringify(
      { tenant_id: data.tenant_id, count: searchResults.value.length },
      null,
      2,
    )
  } catch (error) {
    statusText.value = error.message
  } finally {
    busy.value = false
  }
}

async function submitKnowledge() {
  busy.value = true
  try {
    const doc = {
      title: docTitle.value.trim(),
      content: docContent.value.trim(),
      doc_type: docType.value,
      source: 'frontend_upload',
    }
    const data = await addKnowledge(settings, [doc])
    statusText.value = JSON.stringify(data, null, 2)
    await loadStats()
  } catch (error) {
    statusText.value = error.message
  } finally {
    busy.value = false
  }
}

async function batchImportKnowledge() {
  busy.value = true
  try {
    const data = await importKnowledgeDirectory(settings)
    statusText.value = JSON.stringify(data, null, 2)
    await loadStats()
  } catch (error) {
    statusText.value = error.message
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.hint {
  margin: 0 0 12px;
  font-size: 12px;
  color: #5c6b7d;
  line-height: 1.5;
}

.auth-banner {
  margin-bottom: 12px;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid #f0c36d;
  background: #fff8e6;
  color: #6b4e16;
}

.auth-banner p {
  margin: 6px 0 10px;
  font-size: 13px;
  line-height: 1.45;
}

.auth-banner button {
  width: 100%;
}

.field-hint {
  display: block;
  margin-top: 4px;
  font-size: 11px;
  color: #6b7280;
  line-height: 1.4;
}
</style>
