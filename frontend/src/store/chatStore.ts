import { create } from 'zustand'
import type { ChatMessage, SessionMeta, ToolCall } from '../types/chat'
import type { CouncilEvent } from '../api/council'
import { fetchSSE, SSEClientError } from '../utils/sse'

let seq = 0
const uid = () => `m${Date.now()}_${seq++}`

/* B12 接线（2026-08-20）：sse.ts 的 AbortController+外部 signal 联动已存在但调用没传——
   clear（启航）时 abort 旧流：停止烧钱 + 防旧流事件污染新会话（clear 后旧流 idx=-1 自动丢弃，无 UI 副作用） */
let currentAbort: AbortController | null = null

interface ChatState {
  messages: ChatMessage[]
  sessionId: string
  sessions: SessionMeta[]
  streaming: boolean
  runId: string | null
  restoring: boolean
  /* 先贤会议元信息（M3）：最近一场辩论的 id + 问题（报告"记入记忆"按钮用） */
  debateMeta: { id: string; question: string }
  setDebateMeta: (id: string, question: string) => void
  send: (text: string, file?: { b64: string; name: string }, isRetry?: boolean) => Promise<void>
  retry: (text: string) => Promise<void>
  restore: () => Promise<void>
  loadSessions: () => Promise<void>
  newSession: () => Promise<void>
  openSession: (sid: string) => Promise<void>
  deleteSession: (sid: string) => Promise<boolean>
  appendDebateEvent: (ev: CouncilEvent) => void
  clear: () => void
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  sessionId: localStorage.getItem('lumen_sid') || '',
  sessions: [],
  streaming: false,
  runId: null,
  restoring: false,
  debateMeta: { id: '', question: '' },

  setDebateMeta: (id, question) => set({ debateMeta: { id, question } }),

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
        /* 先贤会议（M3）：合并会话的辩论事件（role='debate' 消息，刷新恢复用） */
        if (Array.isArray(data.debate_events)) {
          for (const d of data.debate_events as { id: number; event: string }[]) {
            try {
              const ev = JSON.parse(d.event) as CouncilEvent
              msgs.push({ id: `d${d.id}`, role: 'debate', content: '', thinking: '', toolCalls: [], done: true, debateEvent: ev })
            } catch {
              /* 单条事件解析失败跳过（fail loud 由日志兜） */
            }
          }
        }
        set({ messages: msgs })
      } else if (Array.isArray(data.debate_events) && data.debate_events.length > 0) {
        /* 会话只有辩论事件没有对话链（极端情况） */
        const msgs: ChatMessage[] = (data.debate_events as { id: number; event: string }[]).map((d) => {
          try {
            const ev = JSON.parse(d.event) as CouncilEvent
            return { id: `d${d.id}`, role: 'debate' as const, content: '', thinking: '', toolCalls: [], done: true, debateEvent: ev }
          } catch {
            return null
          }
        }).filter(Boolean) as ChatMessage[]
        if (msgs.length > 0) set({ messages: msgs })
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

  /* 用户治理权（2026-08-18）：删除会话。删除的是当前会话则重置界面（防继续发到已删会话） */
  deleteSession: async (sid) => {
    try {
      const res = await fetch(`/api/session/${sid}`, { method: 'DELETE' })
      if (!res.ok) return false
      await get().loadSessions()
      if (get().sessionId === sid) {
        localStorage.removeItem('lumen_sid')
        set({ sessionId: '', messages: [], runId: null })
      }
      return true
    } catch {
      return false
    }
  },

  /* 先贤会议（M3）：一条辩论事件 → 消息流中的 debate 消息（与普通消息同流、可回溯；持久化由后端完成） */
  appendDebateEvent: (ev) => {
    set((s) => ({
      messages: [
        ...s.messages,
        { id: uid(), role: 'debate', content: '', thinking: '', toolCalls: [], done: true, debateEvent: ev },
      ],
    }))
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
      const controller = new AbortController()
      currentAbort = controller
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
          const t: ToolCall = { id: ev.id, name: ev.name, status: ev.status, args: ev.args, result: ev.result }
          const existing = ev.id
            ? m.toolCalls.find((x) => x.id === ev.id)
            : m.toolCalls.find((x) => x.name === ev.name && x.status === 'start')
          if (ev.status === 'start' && !existing) m.toolCalls.push(t)
          else if ((ev.status === 'done' || ev.status === 'error') && existing) {
            existing.status = ev.status
            existing.result = ev.result
          }
        } else if (ev.type === 'error') {
          /* #4 后端异常事件（API 失败/超时）→ 消息已落库，可重试；hint=下一步建议（2026-08-20 异常收尾） */
          m.failed = { kind: 'backend', message: ev.message || '请求失败', hint: ev.hint }
          m.done = true
        } else if (ev.type === 'glint') {
          /* 闪光时刻（2026-08-20，拾光=拾到我们没发现的闪光）：收尾提炼的闪光 → 挂最后一条 assistant 消息 */
          m.glint = ev.text
        } else if (ev.type === 'done') {
          m.done = true
          delete m.failed
          set({ sessionId: ev.session_id, runId: null })
          localStorage.setItem('lumen_sid', ev.session_id)
        }
        set({ messages: [...messages] })
      }, { isRetry, signal: controller.signal })
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

  clear: () => {
    /* B12（2026-08-20）：abort 旧流再清空——防旧流继续烧钱 + 污染新会话 */
    currentAbort?.abort()
    currentAbort = null
    set({ messages: [], sessionId: '' })
  },
}))
