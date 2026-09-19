/* M7 多 agent 任务进度 API */
export interface TaskProgress {
  tasks: Record<string, 'pending' | 'done' | 'failed'>
}

export async function fetchTaskProgress(runId: string): Promise<TaskProgress | null> {
  const res = await fetch(`/api/tasks/${runId}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json()
  return data.progress ?? null
}
