/* 学习进度 API */
export interface ProgressData {
  topics: { title: string; status: string; date: string }[]
  streak: number | null
  hasLearningLog: boolean
  memoryCount: number
}

export async function fetchProgress(): Promise<ProgressData> {
  const res = await fetch('/api/progress')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
