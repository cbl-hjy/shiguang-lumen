import { useEffect, useState } from 'react'
import { fetchProgress } from '../api/progress'

/* 连接状态：真实探测后端（5s 轮询 /api/progress），不再用静态绿点 */
export function useConnection() {
  const [online, setOnline] = useState<boolean | null>(null)
  useEffect(() => {
    let alive = true
    const check = async () => {
      try {
        await fetchProgress()
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
