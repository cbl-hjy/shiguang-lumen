import { create } from 'zustand'
import type { ChatMessage, SessionMeta, ToolCall } from '../types/chat'
import { fetchSSE, SSEClientError } from '../utils/sse'

let seq = 0
const uid = () => `m${Date.now()}_${seq++}`

interface ChatState {
  messages: ChatMessage[]
  sessionId: string
  sessions: SessionMeta[]
  streaming: boolean
  runId: string | null
  restoring: boolean
  send: (text: string, file?: { b64: string; name: string }, isRetry?: boolean) => Promise<void>
  retry: (text: string) => Promise<void>
  restore: () => Promise<void>
  loadSessions: () => Promise<void>
  newSession: () => Promise<void>
  openSession: (sid: string) => Promise<void>
  clear: () => void
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  sessionId: localStorage.getItem('lumen_sid') || '',
  sessions: [],
  streaming: false,
  runId: null,
  restoring: false,

  /* 通用：切到某个会话（恢复消息 + 更新 sessionId） */
  openSession: async (sid) => {
    localStorage.setItem('lumen_sid', sid)
    set({ sessionId: sid, messages: [], restoring: true, runId: null })
    try {
      const res = await fetch(`/api/session/${sid}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      if (Array.isArray(data.messages) && data.messages.length > 0) {
        const msgs: ChatMessage[] = (data.messages as Array<{
          role: 'user' | 'assistant'
          content: string
          thinking: string
          toolCalls: ToolCall[]
        }>).map((r, i) => ({
          id: `h${i}_${Date.now()}`,
          role: r.role,
          content: r.content || '',
          thinking: r.thinking || '',
          toolCalls: (r.toolCalls || []).map((t: ToolCall) => ({ ...t, status: 'done' })),
          done: true,
        }))
        set({ messages: msgs })
      }
    } catch {
      /* 恢复失败静默：保持空态，新消息会正常开新会话 */
    } finally {
      set({ restoring: false })
    }
  },

  restore: async () => {
    const sid = get().sessionId
    if (!sid || get().restoring) return
    await get().openSession(sid)
  },

  loadSessions: async () => {
    try {
      const res = await fetch('/api/sessions')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      set({ sessions: data.sessions || [] })
    } catch {
      /* 列表加载失败静默 */
    }
  },

  newSession: async () => {
    try {
      const res = await fetch('/api/session/new', { method: 'POST' })
      const { session_id } = await res.json()
      localStorage.setItem('lumen_sid', session_id)
      set({ sessionId: session_id, messages: [], runId: null })
      await get().loadSessions()
    } catch {
      /* 新建失败：清本地，下次发送会自动建 */
      localStorage.removeItem('lumen_sid')
      set({ sessionId: '', messages: [], runId: null })
    }
  },

  send: async (text, file, isRetry) => {
    if (get().streaming) return
    const userMsg: ChatMessage = {
      id: uid(),
      role: 'user',
      content: text,
      thinking: '',
      toolCalls: [],
      done: true,
    }
    const botMsg: ChatMessage = {
      id: uid(),
      role: 'assistant',
      content: '',
      thinking: '',
      toolCalls: [],
      done: false,
    }
    set((s) => ({
      streaming: true,
      runId: null,
      messages: [...s.messages, userMsg, botMsg],
    }))

    const body: Record<string, unknown> = {
      message: text,
      session_id: get().sessionId || null,
    }
    if (file) {
      body.file_b64 = file.b64
      body.file_name = file.name
    }

    try {
      await fetchSSE('/api/chat', body, (ev) => {
        const { messages } = get()
        const idx = messages.findIndex((m) => m.id === botMsg.id)
        if (idx < 0) return
        const m = messages[idx]
        if (ev.type === 'delta') {
          /* 模型偶发以孤立标点开头（如"，讲…"）——内容为空时跳过纯标点，避免消息以逗号起头 */
          if (m.content === '' && /^[\s，。、；：！？,.;:!?'"''（）()[\]{}…—~-]*$/.test(ev.text)) return
          m.content += ev.text
        } else if (ev.type === 'run') {
          set({ runId: ev.run_id })
        } else if (ev.type === 'thinking') {
          m.thinking += ev.text
        } else if (ev.type === 'tool') {
          const t: ToolCall = { id: ev.id, name: ev.name, status: ev.status, args: ev.args }
          const existing = ev.id
            ? m.toolCalls.find((x) => x.id === ev.id)
            : m.toolCalls.find((x) => x.name === ev.name && x.status === 'start')
          if (ev.status === 'start' && !existing) m.toolCalls.push(t)
          else if (ev.status === 'done' && existing) existing.status = 'done'
        } else if (ev.type === 'error') {
          /* #4 后端异常事件（API 失败/超时）→ 消息已落库，可重试 */
          m.failed = { kind: 'backend', message: ev.message || '请求失败' }
          m.done = true
        } else if (ev.type === 'done') {
          m.done = true
          delete m.failed
          set({ sessionId: ev.session_id, runId: null })
          localStorage.setItem('lumen_sid', ev.session_id)
        }
        set({ messages: [...messages] })
      }, { isRetry, signal: undefined })
    } catch (e) {
      const { messages } = get()
      const idx = messages.findIndex((m) => m.id === botMsg.id)
      if (idx >= 0) {
        const m = messages[idx]
        /* #6 错误分类：timeout/interrupted/network（后端 error 事件走上面分支，这里是网络层失败） */
        const kind = (e as SSEClientError).kind ?? 'network'
        m.failed = { kind, message: (e as Error).message }
        m.done = true
        set({ messages: [...messages] })
      }
    } finally {
      set({ streaming: false })
      get().loadSessions() /* 消息完成后刷新会话列表（标题/计数） */
    }
  },

  /* #6 重试（手动触发，防自动重发扣费）：重发同文本，带 X-Retry 标志后端去重 */
  retry: async (text) => {
    await get().send(text, undefined, true)
  },

  clear: () => set({ messages: [], sessionId: '' }),
}))
