/* SSE 消费：POST 后按行解析 text/event-stream，回调推事件。
   #6 升级：超时（AbortController+定时器）/ 断流检测（流结束但无 done）/ 网络错误分类。
   外部 signal 可联动（组件卸载中断）；X-Retry 标志由调用方传入（重试去重）。 */
import type { SSEEvent } from '../types/chat'

export const SSE_TIMEOUT_MS = 250_000 // 对齐后端总护栏 240s + 缓冲（后端 240 内必发 error/done，250 只是兜底）

export class SSEClientError extends Error {
  kind: 'timeout' | 'interrupted' | 'network' | 'http'
  constructor(kind: 'timeout' | 'interrupted' | 'network' | 'http', message: string) {
    super(message)
    this.kind = kind
  }
}

export async function fetchSSE(
  url: string,
  body: unknown,
  onEvent: (ev: SSEEvent) => void,
  opts?: { isRetry?: boolean; signal?: AbortSignal },
): Promise<void> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), SSE_TIMEOUT_MS)
  const onOuterAbort = () => controller.abort()
  if (opts?.signal) {
    if (opts.signal.aborted) controller.abort()
    else opts.signal.addEventListener('abort', onOuterAbort)
  }

  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (opts?.isRetry) headers['X-Retry'] = '1' // #6 去重：手动重试必带，后端优先认标志

  try {
    let res: Response
    try {
      res = await fetch(url, { method: 'POST', headers, body: JSON.stringify(body), signal: controller.signal })
    } catch (e) {
      if ((e as Error).name === 'AbortError') throw new SSEClientError('timeout', '请求超时（服务处理时间过长，可重试）')
      throw new SSEClientError('network', `网络错误：${(e as Error).message}`)
    }
    if (!res.ok) throw new SSEClientError('http', `HTTP ${res.status}`)
    if (!res.body) throw new SSEClientError('network', 'no stream')

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    let sawDone = false // #6 断流检测：流正常结束但没收到 done = 连接中断（有部分内容要保留）
    for (;;) {
      let value: Uint8Array | undefined
      let done: boolean
      try {
        ;({ done, value } = await reader.read())
      } catch (e) {
        if ((e as Error).name === 'AbortError') throw new SSEClientError('timeout', '请求超时（服务处理时间过长，可重试）')
        throw new SSEClientError('network', `连接中断：${(e as Error).message}`)
      }
      if (done) break
      buf += decoder.decode(value, { stream: true })
      let i: number
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const chunk = buf.slice(0, i)
        buf = buf.slice(i + 2)
        const line = chunk.split('\n').find((l) => l.startsWith('data:'))
        if (!line) continue
        try {
          const ev = JSON.parse(line.slice(5)) as SSEEvent
          if (ev.type === 'done') sawDone = true
          onEvent(ev)
        } catch {
          /* 忽略解析失败的事件 */
        }
      }
    }
    if (!sawDone) {
      // 流正常关闭但全程无 done：后端断流（有部分内容的场景由 chatStore 保留已收文本）
      throw new SSEClientError('interrupted', '连接中断（已收到的内容已保留，可重试）')
    }
  } finally {
    clearTimeout(timer)
    opts?.signal?.removeEventListener('abort', onOuterAbort)
  }
}
