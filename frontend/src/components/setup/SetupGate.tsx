import { useCallback, useEffect, useState } from 'react'
import { getSetupStatus, saveApiKey, type SetupStatus } from '../../api/setup'
import { setToken } from '../../api/auth'
import Logo from '../ui/Logo'

/* 首次运行引导（阶段③，2026-08-25）：无 DeepSeek key 时全屏配置卡。
   流程：输入 key → 校验（后端 /models 轻量验证）→ 服务 1s 后退出、launcher 3s 后重启
   → 轮询重载：服务回来后 status.needs_setup=false → 进入主界面 */

export default function SetupGate({ onDone }: { onDone: () => void }) {
  const [status, setStatus] = useState<SetupStatus | null>(null)
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [restarting, setRestarting] = useState(false)

  useEffect(() => {
    getSetupStatus()
      .then(setStatus)
      .catch(() => setStatus(null))
  }, [])

  /* 保存成功 → 服务重启 → 轮询直到服务回来且不再 needs_setup */
  const waitForReady = useCallback(() => {
    let tries = 0
    const timer = setInterval(async () => {
      tries += 1
      try {
        const s = await getSetupStatus()
        if (!s.needs_setup) {
          clearInterval(timer)
          onDone()
        }
      } catch {
        /* 服务重启中，继续等 */
      }
      if (tries > 30) clearInterval(timer) // 60s 上限，失败则留在引导页（可手动刷新）
    }, 2000)
  }, [onDone])

  const submit = async () => {
    if (!key.trim() || busy) return
    setBusy(true)
    setError('')
    try {
      const r = await saveApiKey(key.trim())
      if (!r.ok) {
        setError(r.error || '保存失败')
        return
      }
      // 2026-08-26 随机 token 加固：setup 响应携带鉴权 token → 存入 localStorage，
      // 重启后 auth.ts 全局 fetch 包装自动带 Bearer（引导期唯一拿 token 的时机）
      if (r.token) setToken(r.token)
      setRestarting(true)
      waitForReady()
    } catch (e) {
      // 2026-08-26 修复"一直校验中"：网络异常/超时导致 fetch 抛错 → busy 必须复位 + 显示错误
      setError(
        '校验请求失败：' + (e instanceof Error ? e.message : String(e)) + '（请检查网络后重试）',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--color-bg)',
        padding: 24,
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: 460,
          background: 'var(--color-surface)',
          border: '1px solid rgba(236,233,225,0.1)',
          borderRadius: 16,
          padding: 32,
        }}
      >
        <div style={{ marginBottom: 20 }}>
          <Logo size="lg" />
        </div>
        <h1 style={{ fontSize: 22, margin: '0 0 8px', color: 'var(--color-ink)' }}>
          {restarting ? '配置完成，正在启动…' : '欢迎使用拾光'}
        </h1>

        {restarting ? (
          <p style={{ color: 'var(--color-ink-muted)', lineHeight: 1.7 }}>
            服务正在自动重启，稍候将进入对话…
          </p>
        ) : (
          <>
            <p style={{ color: 'var(--color-ink-muted)', lineHeight: 1.7, margin: '0 0 20px' }}>
              拾光是本地 AI 学习搭子。首次使用需要配置 DeepSeek API Key （在 platform.deepseek.com
              创建，按量计费，数据只保存在本机）。
            </p>

            {/* 依赖状态 */}
            {status && (
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 8,
                  marginBottom: 20,
                  fontSize: 13,
                }}
              >
                <DepRow label="Ollama 服务" ok={status.ollama_ok} />
                <DepRow label="嵌入模型 bge-m3" ok={status.model_ok} />
                {status.ollama_error && (
                  <p style={{ color: 'var(--color-error, #c0392b)', margin: 0, lineHeight: 1.5 }}>
                    ⚠️ {status.ollama_error}
                  </p>
                )}
              </div>
            )}

            <input
              type="password"
              placeholder="sk-…"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submit()}
              style={{
                width: '100%',
                boxSizing: 'border-box',
                padding: '10px 12px',
                borderRadius: 8,
                border: '1px solid rgba(236,233,225,0.2)',
                background: 'var(--color-elevated)',
                color: 'var(--color-ink)',
                fontSize: 14,
                marginBottom: 12,
              }}
            />
            {error && (
              <p style={{ color: 'var(--color-error)', fontSize: 13, margin: '0 0 12px' }}>
                {error}
              </p>
            )}
            <button
              onClick={submit}
              disabled={busy || !key.trim()}
              style={{
                width: '100%',
                padding: '11px 0',
                borderRadius: 8,
                border: 'none',
                background: 'var(--color-primary)',
                color: 'var(--color-primary-ink)',
                fontSize: 15,
                fontWeight: 600,
                cursor: busy ? 'wait' : 'pointer',
                opacity: busy || !key.trim() ? 0.6 : 1,
              }}
            >
              {busy ? '校验中…' : '保存并开始'}
            </button>
          </>
        )}
      </div>
    </div>
  )
}

function DepRow({ label, ok }: { label: string; ok: boolean }) {
  return (
    <div
      style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--color-ink-muted)' }}
    >
      <span>{label}</span>
      <span style={{ color: ok ? 'var(--color-success)' : 'var(--color-warning)' }}>
        {ok ? '✓ 正常' : '✗ 未就绪'}
      </span>
    </div>
  )
}
