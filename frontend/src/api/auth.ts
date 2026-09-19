/* 鉴权（P0 门锁，2026-08-12 体检 #11）：token 存取 + fetch 全局包装。
   /api/* 自动带 Authorization: Bearer <token>——sse.ts 与所有 api 模块无需各自改（防漏）。
   401 时广播事件，AuthModal 监听后自动弹出。
   2026-08-27 移动端 APK：同一包装解决 API base——内嵌 WebView origin 是
   https://appassets.androidplatform.net，相对 /api 会打到本地；配置服务器地址后
   全局重写为 <base>/api/...（桌面同源模式 base 为空，行为不变）。 */

const TOKEN_KEY = 'shiguang_token'
const API_BASE_KEY = 'shiguang_api_base'

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

/* API 服务器地址（移动端 APK 用）：如 http://<lan-ip>:8000 或 Tailscale IP；空=同源（桌面） */
export function getApiBase(): string {
  try {
    return localStorage.getItem(API_BASE_KEY) || ''
  } catch {
    return ''
  }
}

export function setApiBase(b: string) {
  try {
    const v = b.trim().replace(/\/+$/, '')
    if (v) localStorage.setItem(API_BASE_KEY, v)
    else localStorage.removeItem(API_BASE_KEY)
  } catch {
    /* 忽略 */
  }
}

/* 相对 /api 路径 → 拼上服务器地址；绝对 URL / 同源模式原样返回 */
export function resolveApiUrl(url: string): string {
  if (/^https?:\/\//.test(url)) return url
  const base = getApiBase()
  if (!base) return url
  return base + (url.startsWith('/') ? url : `/${url}`)
}

export const AUTH_REQUIRED_EVENT = 'shiguang-auth-required'

/* ===== 多用户账号体系（2026-08-28 P0-P3）===== */
export interface UserInfo {
  id: string
  nickname: string
  email: string
  is_admin: boolean
  avatar?: string // 2026-08-29：base64 data URI（128px）；空/缺省=未设置
}

const USER_KEY = 'shiguang_user'

export function getCachedUser(): UserInfo | null {
  try {
    const s = localStorage.getItem(USER_KEY)
    return s ? (JSON.parse(s) as UserInfo) : null
  } catch {
    return null
  }
}

export function setCachedUser(u: UserInfo | null) {
  try {
    if (u) localStorage.setItem(USER_KEY, JSON.stringify(u))
    else localStorage.removeItem(USER_KEY)
  } catch {
    /* 忽略 */
  }
}

export async function apiRegister(
  nickname: string,
  email: string,
  password: string,
  inviteCode: string,
): Promise<UserInfo> {
  const res = await fetch('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ nickname, email, password, invite_code: inviteCode }),
  })
  if (!res.ok) {
    const d = await res.json().catch(() => ({}))
    throw new Error((d as { detail?: string }).detail || `注册失败（HTTP ${res.status}）`)
  }
  const d = await res.json()
  setToken((d as { access_token: string }).access_token)
  setCachedUser((d as { user: UserInfo }).user)
  return (d as { user: UserInfo }).user
}

export async function apiLogin(email: string, password: string): Promise<UserInfo> {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) {
    const d = await res.json().catch(() => ({}))
    throw new Error((d as { detail?: string }).detail || `登录失败（HTTP ${res.status}）`)
  }
  const d = await res.json()
  setToken((d as { access_token: string }).access_token)
  setCachedUser((d as { user: UserInfo }).user)
  return (d as { user: UserInfo }).user
}

export async function apiMe(): Promise<UserInfo> {
  const res = await fetch('/api/auth/me')
  if (!res.ok) throw new Error(`获取用户信息失败（HTTP ${res.status}）`)
  const u = (await res.json()) as UserInfo
  setCachedUser(u)
  return u
}

export function logout() {
  setToken('')
  setCachedUser(null)
  window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT))
}

/* 全局 fetch 包装：应用启动时调用一次；覆盖 /api/chat(SSE)、/api/memory 等全部调用。
   API base 重写放这里——sse.ts 与所有 api 模块零改动，一处生效（官方 lw.Web2Android
   要求"构建前设置 API Base URL"，Web 层运行时配置更灵活：IP 变化改设置不用重打包）。 */
export function installAuthFetch() {
  const orig = window.fetch.bind(window)
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const raw =
      typeof input === 'string' ? input : input instanceof URL ? input.href : (input as Request).url
    const url = resolveApiUrl(raw)
    const headers = new Headers(init?.headers)
    if (url.startsWith('/api/') || url.includes('/api/') && !headers.has('Authorization')) {
      const t = getToken()
      if (t) headers.set('Authorization', `Bearer ${t}`)
    }
    // 重写后的绝对 URL 需替换 input，否则 fetch 仍用原相对路径
    // 连接超时（2026-08-29：服务器地址输错时 12s 快速失败给提示，不等浏览器默认超时几分钟）；
    // SSE 长连接（/api/chat 流式）除外——中止会掐断流式回复；调用方已传 signal 则不覆盖
    const isSSE = url.includes('/api/chat')
    let timer: ReturnType<typeof setTimeout> | undefined
    let mergedInit = init
    if (!isSSE && !init?.signal) {
      const controller = new AbortController()
      timer = setTimeout(() => controller.abort(), 12000)
      mergedInit = { ...init, signal: controller.signal }
    }
    try {
      const finalInput: RequestInfo | URL = url !== raw ? url : input
      const res = await orig(finalInput, { ...mergedInit, headers })
      if (res.status === 401 && (url.startsWith('/api/') || url.includes('/api/'))) {
        window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT))
      }
      return res
    } finally {
      if (timer) clearTimeout(timer)
    }
  }
}

export async function updateAvatar(avatar: string): Promise<UserInfo> {
  const res = await fetch('/api/auth/me', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ avatar }),
  })
  if (!res.ok) {
    const d = await res.json().catch(() => ({}))
    throw new Error((d as { detail?: string }).detail || `更新失败（HTTP ${res.status}）`)
  }
  const u = (await res.json()) as UserInfo
  setCachedUser(u)
  return u
}
