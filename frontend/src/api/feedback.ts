/* M8 进化层反馈 API：👎 → 触发反思；👍 → 提示可存技能 */
export async function sendFeedback(rating: -1 | 1, message: string, response?: string): Promise<void> {
  await fetch('/api/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rating, message, response }),
  })
}
