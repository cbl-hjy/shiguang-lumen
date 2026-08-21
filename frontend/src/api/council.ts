/* 先贤会议 API（M3）：星宿列表 / 发起会议(SSE) / 中止 / 人审确认 / 蒸馏 */
import { fetchSSE } from '../utils/sse'
import type { SSEEvent } from '../types/chat'

export interface SageInfo {
  id: string
  name: string
  stance: string
  domain: string
  distill_method: string
  confirmed: boolean
  claims_count: number
}

export interface CouncilTurn {
  type: 'turn'
  round: number
  sage_id: string
  sage_name: string
  speech: string
  words: number
}

export interface CouncilVerdict {
  type: 'verdict'
  round: number
  repeated: boolean
  off_topic: boolean
  new_claims: number
  marginal_gain: boolean
  should_converge: boolean
  notes: string
}

export interface CouncilReport {
  type: 'report'
  actionable: string[]
  consensus: string[]
  divergences: string[]
  complementarities: string[]
  unanswered: string[]
}

export interface CouncilBudget {
  type: 'budget'
  debate_id: string
  sages: string[]
  max_rounds: number
  est_tokens_k: number
  est_cost: string
}

export type CouncilEvent =
  | CouncilBudget
  | { type: 'round_start'; round: number }
  | CouncilTurn
  | CouncilVerdict
  | { type: 'converged'; reason: string }
  | CouncilReport
  | { type: 'stopped'; debate_id: string }
  | { type: 'done'; debate_id: string }

export async function listSages(): Promise<SageInfo[]> {
  const res = await fetch('/api/council/sages')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json()
  return data.sages ?? []
}

export interface DebateMode {
  id: string
  name: string
  desc: string
  sages: { id: string; name: string }[]
  max_rounds: number
  available: boolean
}

export async function fetchModes(): Promise<DebateMode[]> {
  const res = await fetch('/api/council/modes')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json()
  return data.modes ?? []
}

export async function startDebate(
  question: string,
  mode: string,
  maxRounds: number,
  onEvent: (ev: CouncilEvent) => void,
  signal?: AbortSignal,
  sessionId?: string,
  sageIds?: string[], /* 自定义组合（自由定义）：有则传给后端，mode 规则照旧 */
): Promise<void> {
  const body: Record<string, unknown> = { question, mode, max_rounds: maxRounds, session_id: sessionId || null }
  if (sageIds && sageIds.length > 0) body.sage_ids = sageIds
  await fetchSSE(
    '/api/council/debate',
    body,
    onEvent as unknown as (ev: SSEEvent) => void,
    { signal },
  )
}

export async function stopDebate(debateId: string): Promise<void> {
  await fetch(`/api/council/debate/${debateId}/stop`, { method: 'POST' })
}

export async function confirmSage(sageId: string, confirmed = true): Promise<void> {
  await fetch(`/api/council/sages/${sageId}/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirmed }),
  })
}

/* ---- 星阁治理权（2026-08-20 六件套：列表/查看/确认/删除/删观点/改元信息）---- */

export async function fetchSageDetail(sageId: string): Promise<Record<string, unknown>> {
  const r = await fetch(`/api/council/sages/${sageId}`)
  if (!r.ok) throw new Error(`读取星宿失败: ${r.status}`)
  return r.json()
}

export async function deleteSage(sageId: string): Promise<void> {
  const r = await fetch(`/api/council/sages/${sageId}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(`删除失败: ${r.status}`)
}

export async function deleteClaim(sageId: string, idx: number): Promise<void> {
  const r = await fetch(`/api/council/sages/${sageId}/claims/${idx}/delete`, { method: 'POST' })
  if (!r.ok) throw new Error(`删除观点失败: ${r.status}`)
}

export async function updateSageMeta(sageId: string, name?: string, stance?: string): Promise<void> {
  const r = await fetch(`/api/council/sages/${sageId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, stance }),
  })
  if (!r.ok) throw new Error(`更新失败: ${r.status}`)
}

export async function memorizeReport(
  debateId: string,
  question: string,
  actionable: string[],
): Promise<{ memorized: boolean; result?: string }> {
  const res = await fetch('/api/council/report/memorize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ debate_id: debateId, question, actionable, confirmed: true }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export interface DistillStage {
  type: 'stage'
  stage: string
  detail: string
}

export interface DistillRegistered {
  type: 'registered'
  sage_id: string
  claims: number
  quote_verified: number
}

export type DistillEvent = DistillStage | DistillRegistered | { type: 'error'; detail: string }

/* 蒸馏新书（用户自助）：上传书文本 → 星笺（SSE 阶段进度）。
   断点续传（2026-08-20）：jobId 存在 → 续传（text 可空，后端读存盘 raw）。 */
export async function distillBook(
  text: string,
  sageId: string,
  title: string,
  onEvent: (ev: DistillEvent) => void,
  signal?: AbortSignal,
  jobId?: string,
): Promise<void> {
  await fetchSSE(
    '/api/council/distill',
    { text, sage_id: sageId, title, job_id: jobId },
    onEvent as unknown as (ev: SSEEvent) => void,
    { signal },
  )
}

/* 未完成蒸馏任务列表（断点续传入口） */
export async function fetchDistillJobs(): Promise<Array<{
  job_id: string
  sage_id: string
  book_title: string
  created_at: string
  chapters_done: number
  chapters_total: number
}>> {
  const r = await fetch('/api/council/distill/jobs')
  if (!r.ok) throw new Error(`任务列表失败: ${r.status}`)
  const data = await r.json()
  return data.jobs ?? []
}
