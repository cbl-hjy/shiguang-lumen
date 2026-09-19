import { useEffect, useState } from 'react'

/* 连接状态：真实探测后端（5s 轮询 /healthz，公开无鉴权端点）。
   2026-08-28 修正：原用 /api/progress（需 token）——APK 场景 token 未就绪时 401 被误判"离线"；
   healthz 无鉴权，探测结果只反映"网络通不通"，鉴权问题由 401 红点单独表达 */
export function useConnection() {
  const [online, setOnline] = useState<boolean | null>(null)
  useEffect(() => {
    let alive = true
    const check = async () => {
      try {
        // fetch 经全局包装（auth.ts resolveApiUrl）→ APK 内嵌场景自动拼服务器地址
        const res = await fetch('/healthz')
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        if (alive) setOnline(true)
      } catch {
        if (alive) setOnline(false)
      }
    }
    check()
    const t = setInterval(check, 5000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])
  return online
}
