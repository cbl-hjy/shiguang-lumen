/* 聊天类型（与后端 SSE 协议对齐） */
import type { CouncilEvent } from '../api/council'

export interface ToolCall {
  id?: string
  name: string
  status: 'start' | 'done' | 'error'
  args?: string
  /* 可观测性（2026-08-18）：工具返回文本摘要 + 失败标记——结果对用户可见，模型无法吞掉 */
  result?: string
}

export interface SessionMeta {
  id: string
  title: string | null
  created_at: string
  msg_count: number
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'debate' /* debate=先贤会议事件消息（M3） */
  content: string
  thinking: string
  toolCalls: ToolCall[]
  done: boolean
  /* 先贤会议（M3）：role='debate' 时携带事件（预算/发言/判定/报告），与普通消息同流 */
  debateEvent?: CouncilEvent
  /* #6：失败标记（触发重试 UI）。kind 区分错误源——backend=后端 error 事件（已落库）；http=HTTP 状态错误；
     timeout/interrupted/network=网络层失败（可能未落库）。hint=后端给的下一步建议（2026-08-20 异常收尾） */
  failed?: { kind: 'backend' | 'http' | 'timeout' | 'interrupted' | 'network'; message: string; hint?: string }
  /* 闪光时刻（2026-08-20）：收尾提炼"拾到我们没发现的闪光"→ 消息旁金光点（amber + 点亮动画） */
  glint?: string
}

export type SSEEvent =
  | { type: 'delta'; text: string }
  | { type: 'thinking'; text: string }
  | { type: 'tool'; id?: string; name: string; status: 'start' | 'done' | 'error'; args?: string; result?: string }
  | { type: 'turn_start' }
  | { type: 'turn_end' }
  | { type: 'run'; run_id: string }
  | { type: 'done'; session_id: string }
  | { type: 'glint'; text: string }
  | { type: 'error'; message: string; hint?: string }
