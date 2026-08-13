/* 记忆 API（M5 人可审：列表 / 修正 / 删除；M8 扩展：反思 / 技能展示） */
export interface MemoryEntry {
  content: string
  category: string
  importance: number
  date: string
  source: string
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

export async function fetchMemory(): Promise<MemoryData> {
  const res = await fetch('/api/memory')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
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
