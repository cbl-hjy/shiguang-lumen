/* 记忆 API（M5 人可审：列表 / 修正 / 删除；M8 扩展：反思 / 技能展示） */
export interface MemoryEntry {
  content: string
  category: string
  importance: number
  date: string
  source: string
  strength?: number // S 强度（1-5，治理权：显示"用过 N 次"，2026-08-19）
}

export interface EvolveItem {
  id: string
  date: string
  content: string
}

export interface MemoryData {
  profile: string
  entries: MemoryEntry[]
  reflections: EvolveItem[]
  skills: EvolveItem[]
}

/* 记忆变更日志（治理权#3，2026-08-18）：谁改了什么记忆、前后什么样 */
export interface ChangeRecord {
  time: string
  action: string
  summary: string
}

export async function fetchChanges(): Promise<ChangeRecord[]> {
  try {
    const res = await fetch('/api/memory/changes')
    if (!res.ok) return []
    const data = await res.json()
    return data.changes || []
  } catch {
    return []
  }
}

export async function fetchMemory(): Promise<MemoryData> {
  const res = await fetch('/api/memory')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

/** 记忆健康（Phase1 M-4 治理入口，2026-08-29）：访问统计 + 冷记忆预览——数据源 /api/memory/stats */
export interface MemoryStats {
  stats: Record<string, { count: number; last: string }>
  cold_count: number
  cold_preview: { id: string; content: string; category: string; age_days: number; tau: number }[]
  error?: string
}

export async function fetchMemoryStats(): Promise<MemoryStats> {
  const res = await fetch('/api/memory/stats')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

/** 手动休眠单条记忆（Phase1 M-1 治理操作闭环）：退出检索，文件保留可找回 */
export async function demoteMemory(content: string): Promise<boolean> {
  const res = await fetch('/api/memory/demote', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  })
  if (!res.ok) return false
  const d = (await res.json()) as { ok?: boolean }
  return !!d.ok
}

export async function editMemory(oldText: string, newText: string): Promise<void> {
  await fetch('/api/memory/edit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ old: oldText, new: newText }),
  })
}

export async function deleteMemory(content: string): Promise<void> {
  await fetch('/api/memory/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  })
}

export async function editEvolutionItem(
  kind: 'reflection' | 'skill',
  old: string,
  newText: string,
): Promise<void> {
  await fetch('/api/evolution/edit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind, old, new: newText }),
  })
}

export async function deleteEvolutionItem(
  kind: 'reflection' | 'skill',
  content: string,
): Promise<void> {
  await fetch('/api/evolution/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind, content }),
  })
}

/* ===== 记忆治理（2026-08-27 HARNESS-V2 星图第 8 张卡）：id 级操作 + reason + 回收站 ===== */

export interface GovEntry {
  id: string
  content: string
  category: string
  importance: number
  source: string
  created_at: string
  updated_at: string
  strength: number
}

export interface GovData {
  entries: GovEntry[]
  count: number
  categories: Record<string, number>
}

export async function fetchMemoryEntries(category = ''): Promise<GovData> {
  try {
    const res = await fetch(`/api/memory/entries?category=${encodeURIComponent(category)}`)
    if (!res.ok) return { entries: [], count: 0, categories: {} }
    return await res.json()
  } catch {
    return { entries: [], count: 0, categories: {} }
  }
}

export async function editMemoryEntryById(
  id: string,
  newContent: string,
): Promise<{ ok: boolean; msg: string }> {
  try {
    const res = await fetch('/api/memory/entry/edit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, new_content: newContent }),
    })
    return await res.json()
  } catch (e) {
    return { ok: false, msg: String(e) }
  }
}

export async function deleteMemoryEntryById(
  id: string,
  reason = 'user_request',
): Promise<{ ok: boolean; msg: string }> {
  try {
    const res = await fetch('/api/memory/entry/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, reason }),
    })
    return await res.json()
  } catch (e) {
    return { ok: false, msg: String(e) }
  }
}

export async function fetchMemoryTrash(): Promise<string> {
  try {
    const res = await fetch('/api/memory/trash')
    if (!res.ok) return ''
    const data = await res.json()
    return data.text || ''
  } catch {
    return ''
  }
}

export async function fetchMemoryProfile(): Promise<string> {
  try {
    const res = await fetch('/api/memory/profile')
    if (!res.ok) return ''
    const data = await res.json()
    return data.text || ''
  } catch {
    return ''
  }
}

export interface SessionSummary {
  goal: string
  decisions: string[]
  open: string[]
  entities: string[]
  covered_rounds: number
  compacted_at: string
}

export async function fetchSessionSummary(sid: string): Promise<SessionSummary | null> {
  try {
    const res = await fetch('/api/session/' + encodeURIComponent(sid) + '/summary')
    if (!res.ok) return null
    const data = await res.json()
    return data.summary || null
  } catch {
    return null
  }
}
