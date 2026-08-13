/* M6 通知 API：轮询取未读 / 标记已读 */
export interface NotificationItem {
  id: number
  content: string
  is_read: number
  created_at: string
}

export async function fetchNotifications(): Promise<NotificationItem[]> {
  const res = await fetch('/api/notifications')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json()
  return data.notifications ?? []
}

export async function markNotificationRead(id: number): Promise<void> {
  await fetch('/api/notifications/read', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  })
}
