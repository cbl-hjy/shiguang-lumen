/* 首次运行引导（阶段③，2026-08-25）：配置状态查询 + 保存 DeepSeek key */
export interface SetupStatus {
  needs_setup: boolean
  deepseek_configured: boolean
  ollama_ok: boolean
  model_ok: boolean
  ollama_error?: string
}

export interface UpdateStatus {
  update_available: boolean
  version?: string
  url?: string
}

export async function getUpdateStatus(): Promise<UpdateStatus> {
  const res = await fetch('/api/update/status')
  if (!res.ok) return { update_available: false }
  return res.json().catch(() => ({ update_available: false }))
}

export async function getSetupStatus(): Promise<SetupStatus> {
  const res = await fetch('/api/setup/status')
  if (!res.ok) throw new Error(`status ${res.status}`)
  return res.json()
}

export interface SaveApiKeyResult {
  ok: boolean
  error?: string
  restarting?: boolean
  token?: string
}

export async function saveApiKey(apiKey: string): Promise<SaveApiKeyResult> {
  const res = await fetch('/api/setup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key: apiKey }),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) return { ok: false, error: body.error || `status ${res.status}` }
  return body
}
