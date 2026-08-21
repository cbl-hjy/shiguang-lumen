import { useEffect, useRef, useState } from 'react'
import {
  fetchNotifications,
  markNotificationRead,
  type NotificationItem,
} from '../../api/notifications'
import Icon from './Icon'

/* M6 通知投递（双通道）：
   - 页内横幅：始终可用（兜底，手机/非安全上下文都行）
   - 浏览器 Notification：PC 安全上下文（localhost/127.0.0.1）额外推送
   轮询 8s；只弹"新出现"的通知（首次加载的历史未读不弹，避免打扰） */
export default function NotificationBanner() {
  const [queue, setQueue] = useState<NotificationItem[]>([])
  const [current, setCurrent] = useState<NotificationItem | null>(null)
  const seenRef = useRef<Set<number>>(new Set())

  /* 首次挂载：吸收历史未读（不弹），并请求一次通知权限（等用户首次交互） */
  useEffect(() => {
    const absorb = async () => {
      try {
        const items = await fetchNotifications()
        items.forEach((i) => seenRef.current.add(i.id))
      } catch {
        /* 后端离线不打扰 */
      }
    }
    absorb()
    const requestPerm = () => {
      if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission().catch(() => {})
      }
    }
    window.addEventListener('click', requestPerm, { once: true })
    return () => window.removeEventListener('click', requestPerm)
  }, [])

  /* 轮询新通知 → 入队 */
  useEffect(() => {
    const poll = async () => {
      try {
        const items = await fetchNotifications()
        const fresh = items.filter(
          (i) => !i.is_read && !seenRef.current.has(i.id),
        )
        if (fresh.length) {
          fresh.forEach((i) => seenRef.current.add(i.id))
          setQueue((q) => [...q, ...fresh])
        }
      } catch {
        /* 忽略轮询失败 */
      }
    }
    const timer = setInterval(poll, 8000)
    return () => clearInterval(timer)
  }, [])

  /* 队列 → 逐条展示（浏览器通知 + 横幅） */
  useEffect(() => {
    if (current || queue.length === 0) return
    const next = queue[0]
    setQueue((q) => q.slice(1))
    setCurrent(next)
    if ('Notification' in window && Notification.permission === 'granted') {
      try {
        new Notification('拾光 · 提醒', { body: next.content, silent: true })
      } catch {
        /* 忽略推送失败，横幅兜底 */
      }
    }
  }, [queue, current])

  const dismiss = () => {
    if (current) markNotificationRead(current.id).catch(() => {})
    setCurrent(null)
  }

  if (!current) return null

  return (
    <div className="fixed top-14 right-4 z-40 max-w-sm animate-msg-in" role="status" aria-live="polite">
      <div className="relative rounded-xl bg-elevated border border-hairline shadow-2xl overflow-hidden glow-primary">
        <div className="absolute inset-y-0 left-0 w-[3px] top-accent-line" />
        <div className="flex items-start gap-3 pl-4 pr-3 py-3">
          {/* 提醒之光：拾光来提醒你 = 一盏灯亮起 */}
          <div className="relative mt-1 shrink-0 w-7 h-7 rounded-lg bg-primary/15 flex items-center justify-center">
            <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-primary shadow-[0_0_6px_rgba(62,201,176,0.9)] animate-flame" />
            <Icon name="bell" size={15} className="text-primary" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-[12px] font-medium text-ink mb-0.5">
              拾光记得你
            </div>
            <p className="text-[13px] leading-relaxed text-ink-muted">
              {current.content}
            </p>
          </div>
          <button
            onClick={dismiss}
            className="shrink-0 p-1 rounded-md text-ink-dim hover:text-ink/85 hover:bg-surface transition-colors duration-150"
            aria-label="关闭提醒"
          >
            <Icon name="x" size={14} />
          </button>
        </div>
        <button
          onClick={dismiss}
          className="w-full py-1.5 text-[11px] text-primary/80 hover:text-primary bg-primary/5 hover:bg-primary/10 transition-colors duration-150"
        >
          已看到，去学习
        </button>
      </div>
    </div>
  )
}
