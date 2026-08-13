import { useEffect, useState } from 'react'
import Logo from './components/ui/Logo'
import Icon from './components/ui/Icon'
import CommandPalette from './components/ui/CommandPalette'
import NotificationBanner from './components/ui/NotificationBanner'
import AuthModal from './components/ui/AuthModal'
import ChatStream from './components/chat/ChatStream'
import InputBar from './components/chat/InputBar'
import SessionDrawer from './components/chat/SessionDrawer'
import PathPanel from './components/path/PathPanel'
import MemoryPanel from './components/memory/MemoryPanel'
import { useConnection } from './hooks/useConnection'
import { useChatStore } from './store/chatStore'
import { useUiStore } from './store/uiStore'

/* 布局（瘦身版）：左=路径/记忆(tab) · 中=聊天
   ≡ 按钮一键收缩/弹出左栏（专注聊天）
   移动端 <md：单栏聊天 + 抽屉切换（路径/记忆） */

type Drawer = 'path' | 'memory' | null

export default function App() {
  const messages = useChatStore((s) => s.messages)
  const restore = useChatStore((s) => s.restore)
  const sessions = useChatStore((s) => s.sessions)
  const sessionId = useChatStore((s) => s.sessionId)
  const loadSessions = useChatStore((s) => s.loadSessions)
  const newSession = useChatStore((s) => s.newSession)
  const openSession = useChatStore((s) => s.openSession)
  const online = useConnection()
  const [drawer, setDrawer] = useState<Drawer>(null)
  const [sessionOpen, setSessionOpen] = useState(false)
  const [authOpen, setAuthOpen] = useState(false) // 连接令牌设置入口（P0 门锁）
  const [leftOpen, setLeftOpen] = useState(true) // 左栏开关（≡ 一键收缩/弹出）
  const setCommandOpen = useUiStore((s) => s.setCommandOpen)

  /* 刷新后恢复会话（A：会话持久性——localStorage 有 session_id 就拉回历史消息） */
  useEffect(() => {
    restore()
    loadSessions()
  }, [restore, loadSessions])

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

  const connText = online === null ? '连接中…' : online ? '已连接' : '后端离线'
  const connDot = online === null ? 'bg-warning' : online ? 'bg-success' : 'bg-error'

  return (
    <div className="h-full flex flex-col bg-bg relative">
      {/* 光束：左上角灯斜射（零动画，强化光源方向感——光=状态非表演） */}
      <div className="beam" aria-hidden />
      <header className="h-12 shrink-0 border-b border-hairline flex items-center justify-between px-4 relative z-10">
        <div className="flex items-center gap-2">
          <Logo />
          {/* 桌面端：≡ 左栏开关 + 会话历史 */}
          <div className="hidden md:flex gap-1 ml-1">
            <button
              onClick={() => setLeftOpen((v) => !v)}
              className={`p-1.5 rounded-lg transition-colors duration-150 ${
                leftOpen
                  ? 'text-primary/80 hover:text-primary hover:bg-elevated'
                  : 'text-[rgba(236,233,225,0.35)] hover:text-primary hover:bg-elevated'
              }`}
              aria-label={leftOpen ? '收起侧边栏' : '展开侧边栏'}
              title={leftOpen ? '收起侧边栏（沉浸聊天）' : '展开侧边栏'}
            >
              <Icon name="panels" size={16} />
            </button>
            <button
              onClick={() => setSessionOpen(true)}
              className="p-1.5 rounded-lg text-[rgba(236,233,225,0.5)] hover:text-primary hover:bg-elevated transition-colors duration-150"
              aria-label="会话历史"
              title="会话历史"
            >
              <Icon name="history" size={16} />
            </button>
          </div>
          {/* 移动端抽屉切换 */}
          <div className="flex gap-1 md:hidden">
            <button
              onClick={() => setDrawer(drawer === 'path' ? null : 'path')}
              className="p-1.5 rounded-lg text-[rgba(236,233,225,0.5)] hover:text-primary hover:bg-elevated transition-colors duration-150"
              aria-label="学习路径"
            >
              <Icon name="book" size={16} />
            </button>
            <button
              onClick={() => setDrawer(drawer === 'memory' ? null : 'memory')}
              className="p-1.5 rounded-lg text-[rgba(236,233,225,0.5)] hover:text-primary hover:bg-elevated transition-colors duration-150"
              aria-label="记忆"
            >
              <Icon name="brain" size={16} />
            </button>
          </div>
        </div>
        <div className="flex items-center gap-2 text-[12px] text-[rgba(236,233,225,0.55)]">
          <button
            onClick={() => setAuthOpen(true)}
            className="p-1.5 rounded-lg hover:text-primary hover:bg-elevated transition-colors duration-150"
            aria-label="连接设置"
            title="连接设置（令牌）"
          >
            <Icon name="wrench" size={14} />
          </button>
          <span className={`inline-block w-2 h-2 rounded-full ${connDot} animate-pulse`} />
          <span>{connText}</span>
        </div>
        <div className="absolute bottom-[-1px] left-0 right-0 top-accent-line" />
      </header>
      <div className="flex-1 flex min-h-0">
        {/* h-full 关键：shrink-0 div 是 flex item 被 stretch 撑满，内部组件需 h-full 才受高度约束 */}
        {leftOpen && (
          <div className="hidden md:block shrink-0 h-full">
            <PathPanel />
          </div>
        )}
        {/* min-h-0 关键：flex 子项默认 min-height:auto 不收缩，缺它 ChatStream 的 overflow 失效 → 内容撑破被 body 裁切 */}
        <main className="flex-1 flex flex-col min-w-0 min-h-0 main-grid-bg">
          <ChatStream messages={messages} />
          <InputBar />
        </main>
      </div>

      {/* 移动端抽屉 */}
      {drawer && (
        <div className="fixed inset-0 z-50 md:hidden" role="dialog" aria-modal="true">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setDrawer(null)}
            aria-label="关闭面板"
          />
          <div className="absolute inset-y-0 left-0 w-72 bg-bg shadow-2xl animate-msg-in overflow-y-auto">
            {drawer === 'path' ? <PathPanel /> : <MemoryPanel />}
          </div>
        </div>
      )}

      {/* Cmd+K 命令面板 */}
      <CommandPalette onOpenPanel={setDrawer} />

      {/* M6 通知横幅（双通道：页内 + 浏览器 Notification） */}
      <NotificationBanner />

      {/* P0 门锁：连接令牌设置（手动按钮 / 401 自动弹出） */}
      <AuthModal open={authOpen} onOpenChange={setAuthOpen} />

      {/* B：会话历史抽屉（DeepSeek 式） */}
      <SessionDrawer
        open={sessionOpen}
        sessions={sessions}
        currentId={sessionId}
        onClose={() => setSessionOpen(false)}
        onNew={() => {
          newSession()
          setSessionOpen(false)
        }}
        onOpen={(sid) => {
          openSession(sid)
          setSessionOpen(false)
        }}
      />
    </div>
  )
}
