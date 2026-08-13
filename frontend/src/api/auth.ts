/* 鉴权（P0 门锁，2026-08-12 体检 #11）：token 存取 + fetch 全局包装。
   /api/* 自动带 Authorization: Bearer <token>——sse.ts 与所有 api 模块无需各自改（防漏）。
   401 时广播事件，AuthModal 监听后自动弹出。 */

const TOKEN_KEY = 'shiguang_token'

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

export function setToken(t: string) {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* 隐私模式等场景忽略 */
  }
}

export const AUTH_REQUIRED_EVENT = 'shiguang-auth-required'

/* 全局 fetch 包装：应用启动时调用一次；覆盖 /api/chat(SSE)、/api/memory 等全部调用 */
export function installAuthFetch() {
  const orig = window.fetch.bind(window)
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.href
          : (input as Request).url
    const headers = new Headers(init?.headers)
    if (url.startsWith('/api/') && !headers.has('Authorization')) {
      const t = getToken()
      if (t) headers.set('Authorization', `Bearer ${t}`)
    }
    const res = await orig(input, { ...init, headers })
    if (res.status === 401 && url.startsWith('/api/')) {
      window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT))
    }
    return res
  }
}
