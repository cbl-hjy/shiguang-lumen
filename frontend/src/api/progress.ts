/* 学习进度 API（Memory Hub 聚合视图，2026-08-19） */
export interface TopicMemory {
  content: string
  category: string
  date: string
  content_date?: string
}

export interface Topic {
  name: string
  parent: string
  status: string
  last_active: string
  memory_count: number
  memories: TopicMemory[]
  continuation?: { text: string; from_date: string; abandoned: boolean }
  reflections?: string[]
  skills?: string[]
}

/* 主题纠错（P3）：改名/合并——改索引零迁移（记忆文件不动） */
export async function renameTopic(oldName: string, newName: string): Promise<{ ok: boolean; msg?: string }> {
  const res = await fetch('/api/topics/rename', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ old: oldName, new: newName }),
  })
  return res.json()
}

export async function mergeTopics(fromName: string, toName: string): Promise<{ ok: boolean; msg?: string }> {
  const res = await fetch('/api/topics/merge', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ from_name: fromName, to_name: toName }),
  })
  return res.json()
}

export async function splitTopic(source: string, newName: string, aliases: string[]): Promise<{ ok: boolean; msg?: string }> {
  const res = await fetch('/api/topics/split', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source, new_name: newName, aliases }),
  })
  return res.json()
}

export interface ProgressData {
  topics: Topic[]
  profile: string
  stats: {
    total: number
    unclassified: number
    topic_count: number
  }
  streak: number | null
  hasLearningLog: boolean
  memoryCount: number
  memory_soft_limit?: number
  memory_hard_limit?: number
  week_days?: number
  week_target?: number
  week_progress?: number
}

export async function fetchProgress(): Promise<ProgressData> {
  const res = await fetch('/api/progress')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
