import { lazy, Suspense, useEffect, useState } from 'react'
import Logo from './components/ui/Logo'
import Icon from './components/ui/Icon'
import ErrorBoundary from './components/ui/ErrorBoundary'
import SessionRail from './components/ui/SessionRail'
import CommandPalette from './components/ui/CommandPalette'
import NotificationBanner from './components/ui/NotificationBanner'
import AuthPage from './components/ui/AuthPage'
import { initTheme, getCustomBg } from './lib/theme'
import ChatStream from './components/chat/ChatStream'
import InputBar from './components/chat/InputBar'
import Starfield from './components/ui/Starfield'
import SetupGate from './components/setup/SetupGate'
import { getSetupStatus, getUpdateStatus, type UpdateStatus } from './api/setup'
import {
  AUTH_REQUIRED_EVENT,
  getCachedUser,
  getToken,
  setCachedUser,
  setToken,
  type UserInfo,
} from './api/auth'
import { useConnection } from './hooks/useConnection'
import { useChatStore } from './store/chatStore'
import { useUiStore } from './store/uiStore'

/* 2026-08-28 性能优化：非首屏大组件全部 React.lazy 按需加载——
   StarMap(2920行)/SettingsPage/MeDrawer/SessionDrawer 不再进首屏 bundle（首屏只留聊天核心）。
   代价：首次打开对应面板多一次网络请求（本地服务毫秒级），换取首屏 JS 减 ~70%。 */
const StarMap = lazy(() => import('./components/starmap/StarMap'))
const SessionDrawer = lazy(() => import('./components/chat/SessionDrawer'))
const SettingsPage = lazy(() => import('./components/ui/SettingsPage'))
const MeDrawer = lazy(() => import('./components/ui/MeDrawer'))

/* 布局（v3 聚合 2026-08-26）：左=历史记录栏（唯一侧栏）· 中=对话（内容居中 720px）
   所有功能收进右上角星图（点卡星图内二级视图就地呈现，不拉出旧组件） */

/* 主题初始化（设置页三套内置背景，2026-08-28）：模块加载即应用持久化主题 */
if (typeof document !== 'undefined') initTheme()

/* 最外层防线（2026-08-29 白屏事故后补）：整个应用包一层 ErrorBoundary。
   任何未捕获的 render 异常（含 setup/登录/设置/「它记得我」各分支）都退化成
   一张错误卡 + 重试按钮，而不是 React 18 卸载整棵树后"只剩背景"。 */
export default function App() {
  return (
    <ErrorBoundary label="拾光">
      <AppShell />
    </ErrorBoundary>
  )
}

function AppShell() {
  const messages = useChatStore((s) => s.messages)
  const restore = useChatStore((s) => s.restore)
  const loadSessions = useChatStore((s) => s.loadSessions)
  const sessions = useChatStore((s) => s.sessions)
  const currentId = useChatStore((s) => s.sessionId)
  const newSession = useChatStore((s) => s.newSession)
  const openSession = useChatStore((s) => s.openSession)
  const deleteSession = useChatStore((s) => s.deleteSession)
  const online = useConnection()
  const [starMapOpen, setStarMapOpen] = useState(false) // 星图面板（v3：一个世界所有功能）
  const [customBg, setCustomBgState] = useState(() => getCustomBg()) // 2026-08-29 自定义背景
  const [historyOpen, setHistoryOpen] = useState(false) // 移动端夜谈记录抽屉（桌面用 SessionRail）

  /* P3 多用户登录态（2026-08-28）：无 JWT → 全屏登录/注册页；401 → 清除凭据回登录页 */
  const [authed, setAuthed] = useState(() => !!getToken())
  const [settingsOpen, setSettingsOpen] = useState(false) // 设置页（产品化整改 2026-08-28）
  const [meOpen, setMeOpen] = useState(false) // 「它记得我」抽屉（前端重构：取代星图为主入口）
  const [user, setUser] = useState<UserInfo | null>(() => getCachedUser())

  /* 2026-08-29：设置页关闭后重读自定义背景 + 用户信息（头像上传/移除即时生效） */
  useEffect(() => {
    if (!settingsOpen) {
      setCustomBgState(getCustomBg())
      setUser(getCachedUser())
    }
  }, [settingsOpen])

  /* 401 → 清凭据回登录页（原"红点提示"升级：多用户下未认证=未登录，直接引导登录） */
  useEffect(() => {
    const onAuth = () => {
      // 401 → 清凭据回登录页（多用户下未认证=未登录；服务器地址由登录页统一配置）
      setToken('')
      setCachedUser(null)
      setAuthed(false)
    }
    window.addEventListener(AUTH_REQUIRED_EVENT, onAuth)
    return () => window.removeEventListener(AUTH_REQUIRED_EVENT, onAuth)
  }, [])
  const setCommandOpen = useUiStore((s) => s.setCommandOpen)

  /* 刷新后恢复夜谈（A：夜谈持久性——localStorage 有 session_id 就拉回历史消息） */
  useEffect(() => {
    if (!authed) return
    restore()
    loadSessions()
  }, [authed, restore, loadSessions])

  /* 全局快捷键：Ctrl/Cmd+K 打开命令面板 */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setCommandOpen(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setCommandOpen])

  const connText = online === null ? '接光中…' : online ? '已接光' : '后端离线'
  const connDot = online === null ? 'bg-warning' : online ? 'bg-success' : 'bg-error'

  /* 首次运行引导（阶段③，2026-08-25）：无 DeepSeek key → 全屏配置卡替代主界面 */
  const [setupOpen, setSetupOpen] = useState(false)
  useEffect(() => {
    getSetupStatus()
      .then((s) => setSetupOpen(s.needs_setup))
      .catch(() => setSetupOpen(false))
  }, [])

  /* 更新检查横幅（2026-08-26 P1：轻量更新源，Inno 版无 velopack 自动更新） */
  const [updateInfo, setUpdateInfo] = useState<UpdateStatus | null>(null)
  useEffect(() => {
    getUpdateStatus()
      .then(setUpdateInfo)
      .catch(() => setUpdateInfo(null))
  }, [])

  /* 构建版本哨兵（2026-08-27：读取 index 响应头 X-Built-At——手机若一直显示旧时间=缓存没刷新，一眼可查） */
  const [builtAt, setBuiltAt] = useState('')
  useEffect(() => {
    fetch(window.location.pathname || '/', { method: 'HEAD' })
      .then((r) => {
        const b = r.headers.get('X-Built-At') || ''
        setBuiltAt(b ? b.slice(5, 16) : '') // MM-DD HH:MM
      })
      .catch(() => {})
  }, [])
  if (setupOpen) {
    return <SetupGate onDone={() => setSetupOpen(false)} />
  }

  if (meOpen) {
    return (
      <Suspense fallback={<LazyFallback label="它记得我" />}>
        <MeDrawer user={user} onClose={() => setMeOpen(false)} />
      </Suspense>
    )
  }

  if (settingsOpen) {
    return (
      <Suspense fallback={<LazyFallback label="设置" />}>
        <SettingsPage
          user={user}
          onClose={() => setSettingsOpen(false)}
          onLogout={() => {
            setAuthed(false)
            setUser(null)
          }}
          onOpenStarMap={() => {
            setSettingsOpen(false)
            setStarMapOpen(true)
          }}
        />
      </Suspense>
    )
  }

  /* P3 登录门（2026-08-28）：未登录 → 全屏登录/注册页（在 setup 之后） */
  if (!authed) {
    return (
      <AuthPage
        onAuthed={() => setAuthed(true)}
      />
    )
  }

  return (
    <div className="h-full flex flex-col relative">
      {/* 自定义背景（2026-08-29）：用户上传图铺底 + 暗化遮罩保文字可读；无则不渲染 */}
      {customBg && <div className="custom-bg" style={{ backgroundImage: `url(${customBg})` }} aria-hidden />}
      {/* 光束：左上角灯斜射（零动画，强化光源方向感——光=状态非表演） */}
      <div className="beam" aria-hidden />
      {/* 极光漂移层（v3 动效：背景缓慢流动，增强沉浸氛围） */}
      <div className="aurora-drift" aria-hidden />
      {/* 星星粒子层（v4：Canvas 自写 ~4KB 替代 Three.js；DPR≤2 + 不可见即停 + reduced-motion 静态帧） */}
      <Starfield />
      {/* grain 噪声（v4 材质：Dark Glassmorphism 质感层，静止零开销） */}
      <div className="grain-overlay" aria-hidden />
      {updateInfo?.update_available && (
        <a
          href={updateInfo.url || '#'}
          target="_blank"
          rel="noreferrer"
          style={{
            display: 'block',
            background: 'var(--color-primary, #3b82f6)',
            color: '#fff',
            fontSize: 13,
            padding: '6px 16px',
            textAlign: 'center',
          }}
        >
          发现新版本 {updateInfo.version}，点击下载安装（数据自动保留）
        </a>
      )}
      <header
        className="min-h-12 shrink-0 border-b border-hairline glass flex items-center justify-between px-4 relative z-10"
        style={{ paddingTop: 'env(safe-area-inset-top)' }}
      >
        <div className="flex items-center gap-2">
          {/* 移动端夜谈记录入口（2026-08-27 实测补：SessionRail 桌面专属，窄屏需替代入口） */}
          <button
            onClick={() => setHistoryOpen(true)}
            className="md:hidden p-2.5 rounded-lg text-ink-muted hover:text-primary hover:bg-elevated transition-colors duration-150"
            aria-label="夜谈记录"
            title="夜谈记录"
          >
            <Icon name="history" size={16} />
          </button>
          <Logo />
        </div>
        <div className="flex items-center gap-2 text-[12px] text-ink-dim">
          {/* 星图按钮（v3：一个世界所有功能） */}
          <button
            onClick={() => setMeOpen(true)}
            className="group relative flex items-center gap-1.5 rounded-full border border-hairline bg-surface px-3.5 py-1.5 text-[12px] text-ink-muted transition-all duration-300 overflow-hidden active:scale-95 hover:text-primary hover:border-transparent hover:shadow-[0_0_20px_rgba(62,201,176,.12),0_0_0_4px_rgba(62,201,176,.06)]"
            aria-label="它记得我"
            title="它记得我（画像 · 记忆 · 路径 · 成长）"
          >
            <svg
              className="w-3.5 h-3.5 transition-transform duration-500 group-hover:rotate-90 group-hover:scale-110"
              viewBox="0 0 24 24"
              fill="none"
            >
              <path
                d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinejoin="round"
              />
            </svg>
            它记得我
          </button>
          <span className={`inline-block w-2 h-2 rounded-full ${connDot} animate-pulse`} />
          <span>{connText}</span>
          {/* 构建版本哨兵：看到旧时间=手机还在用缓存，需强制刷新（2026-08-27 缓存诊断） */}
          {builtAt && <span className="text-[10px] text-ink-dim/60">{builtAt}</span>}
          {/* P3 当前用户 + 退出（2026-08-28） */}
          {user && (
            <>
              <button
                onClick={() => setSettingsOpen(true)}
                className="flex items-center gap-1.5 max-w-[130px] text-[11px] text-ink-dim hover:text-ink px-1.5 py-1 -my-1 rounded-md hover:bg-surface transition-colors duration-150"
                title="打开设置（账号 / 外观 / 服务器 / 退出）"
                aria-label="打开设置"
              >
                {user.avatar ? (
                  <img
                    src={user.avatar}
                    alt=""
                    className="w-5 h-5 rounded-full object-cover border border-hairline shrink-0"
                  />
                ) : (
                  <span className="w-5 h-5 rounded-full bg-elevated border border-hairline flex items-center justify-center text-[10px] shrink-0">
                    {(user.nickname || '?').slice(0, 1)}
                  </span>
                )}
                <span className="truncate">{user.nickname}</span>
              </button>
              <button
                onClick={() => setSettingsOpen(true)}
                className="p-1.5 -my-1 rounded-lg text-ink-dim hover:text-ink hover:bg-surface transition-colors duration-150"
                aria-label="设置"
                title="设置"
              >
                <Icon name="settings" size={14} />
              </button>
            </>
          )}
        </div>
        <div className="absolute bottom-[-1px] left-0 right-0 top-accent-line" />
      </header>
      <div className="flex-1 flex min-h-0">
        {/* 侧边栏只保留历史记录（2026-08-26 用户明确：旧组件该删就删，其余全进星图） */}
        <SessionRail />
        {/* min-h-0 关键：flex 子项默认 min-height:auto 不收缩，缺它 ChatStream 的 overflow 失效 → 内容撑破被 body 裁切 */}
        <main className="flex-1 flex flex-col min-w-0 min-h-0">
          <ChatStream messages={messages} />
          <InputBar />
        </main>
      </div>

      {/* Cmd+K 命令面板（路径/记忆入口已由星图承接，onOpenPanel 打开星图） */}
      <CommandPalette
        onOpenPanel={() => {
          setStarMapOpen(true)
        }}
        onOpenDebate={() => {
          setStarMapOpen(true) /* 问星入口收进星图（星阁→发起辩论） */
        }}
      />

      {/* 星图（v3）：一个世界，所有功能——8 卡承载全部入口，点击关闭并落到对应面板 */}
      <Suspense fallback={<LazyFallback label="星图" />}>
        <StarMap open={starMapOpen} onClose={() => setStarMapOpen(false)} />
      </Suspense>

      {/* M6 通知横幅（双通道：页内 + 浏览器 Notification） */}
      <NotificationBanner />

      {/* 移动端夜谈记录抽屉（2026-08-27：SessionRail 桌面专属，窄屏走抽屉） */}
      <Suspense fallback={null}>
        <SessionDrawer
          open={historyOpen}
          sessions={sessions}
          currentId={currentId}
          onClose={() => setHistoryOpen(false)}
          onNew={() => {
            setHistoryOpen(false)
            newSession()
          }}
          onOpen={(sid) => {
            setHistoryOpen(false)
            openSession(sid)
          }}
          onDelete={async (sid) => {
            await deleteSession(sid)
        }}
      />
      </Suspense>

    </div>
  )
}

/* 懒加载 fallback（2026-08-28 性能优化）：大面板按需加载期间的轻量占位——零动画零网络 */
function LazyFallback({ label }: { label: string }) {
  return (
    <div className="h-full flex flex-col items-center justify-center gap-3 text-ink-dim">
      <span className="text-[12px] tracking-widest">{label}…</span>
    </div>
  )
}
