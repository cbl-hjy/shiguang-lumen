/* 聊天类型（与后端 SSE 协议对齐） */

export interface ToolCall {
  id?: string
  name: string
  status: 'start' | 'done'
  args?: string
}

export interface SessionMeta {
  id: string
  title: string | null
  created_at: string
  msg_count: number
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  thinking: string
  toolCalls: ToolCall[]
  done: boolean
  /* #6：失败标记（触发重试 UI）。kind 区分错误源——backend=后端 error 事件（已落库）；http=HTTP 状态错误；
     timeout/interrupted/network=网络层失败（可能未落库） */
  failed?: { kind: 'backend' | 'http' | 'timeout' | 'interrupted' | 'network'; message: string }
}

export type SSEEvent =
  | { type: 'delta'; text: string }
  | { type: 'thinking'; text: string }
  | { type: 'tool'; id?: string; name: string; status: 'start' | 'done'; args?: string }
  | { type: 'turn_start' }
  | { type: 'turn_end' }
  | { type: 'run'; run_id: string }
  | { type: 'done'; session_id: string }
  | { type: 'error'; message: string }
