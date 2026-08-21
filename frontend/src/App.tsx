import { useCallback, useEffect, useState } from 'react'
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
import DebateView from './components/council/DebateView'
import SageLibraryModal from './components/council/SageLibraryModal'
import { useConnection } from './hooks/useConnection'
import { useChatStore } from './store/chatStore'
import { useUiStore } from './store/uiStore'
import { listSages } from './api/council'

/* 布局（瘦身版）：左=路径(tab) · 中=聊天（含问星——聊天框"会议"按钮弹出配置，主区流式展示）
   ≡ 按钮一键收缩/弹出左栏（专注聊天）
   移动端 <md：单栏聊天 + 抽屉切换（路径/星尘） */

type Drawer = 'path' | 'memory' | null

export default function App() {
  const messages = useChatStore((s) => s.messages)
  const restore = useChatStore((s) => s.restore)
  const sessions = useChatStore((s) => s.sessions)
  const sessionId = useChatStore((s) => s.sessionId)
  const loadSessions = useChatStore((s) => s.loadSessions)
  const newSession = useChatStore((s) => s.newSession)
  const openSession = useChatStore((s) => s.openSession)
  const deleteSession = useChatStore((s) => s.deleteSession)
  const online = useConnection()
  const [drawer, setDrawer] = useState<Drawer>(null)
  const [sessionOpen, setSessionOpen] = useState(false)
  const [authOpen, setAuthOpen] = useState(false) // 接光令牌调光入口（P0 门锁）
  const [leftOpen, setLeftOpen] = useState(true) // 左栏开关（≡ 一键收缩/弹出）
  const [debateVisible, setDebateVisible] = useState(false) // 问星 popover（聊天框按钮 toggle）
  const [sageLibOpen, setSageLibOpen] = useState(false) // 星阁管理窗（治理权六件套，2026-08-20）
  const [sagesPending, setSagesPending] = useState(0) // 待审计数（入口信号 B，2026-08-20：有事一眼可见）

  /* 入口状态信号：拉星阁待审计数（打开会议/确认卡后刷新） */
  const refreshPending = useCallback(() => {
    listSages()
      .then((s) => setSagesPending(s.filter((x) => !x.confirmed).length))
      .catch(() => setSagesPending(0))
  }, [])
  useEffect(() => {
    refreshPending()
  }, [refreshPending, debateVisible, sageLibOpen])
  const setCommandOpen = useUiStore((s) => s.setCommandOpen)

  /* 刷新后恢复夜谈（A：夜谈持久性——localStorage 有 session_id 就拉回历史消息） */
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

  const connText = online === null ? '接光中…' : online ? '已接光' : '后端离线'
  const connDot = online === null ? 'bg-warning' : online ? 'bg-success' : 'bg-error'

  return (
    <div className="h-full flex flex-col bg-bg relative">
      {/* 光束：左上角灯斜射（零动画，强化光源方向感——光=状态非表演） */}
      <div className="beam" aria-hidden />
      <header className="h-12 shrink-0 border-b border-hairline flex items-center justify-between px-4 relative z-10">
        <div className="flex items-center gap-2">
          <Logo />
          {/* 桌面端：≡ 左栏开关 + 夜谈记录 */}
          <div className="hidden md:flex gap-1 ml-1">
            <button
              onClick={() => setLeftOpen((v) => !v)}
              className={`p-1.5 rounded-lg transition-colors duration-150 ${
                leftOpen
                  ? 'text-primary/80 hover:text-primary hover:bg-elevated'
                  : 'text-ink-dim/80 hover:text-primary hover:bg-elevated'
              }`}
              aria-label={leftOpen ? '收起侧边栏' : '展开侧边栏'}
              title={leftOpen ? '收起侧边栏（沉浸聊天）' : '展开侧边栏'}
            >
              <Icon name="panels" size={16} />
            </button>
            <button
              onClick={() => setSessionOpen(true)}
              className="p-1.5 rounded-lg text-ink-dim hover:text-primary hover:bg-elevated transition-colors duration-150"
              aria-label="夜谈记录"
              title="夜谈记录"
            >
              <Icon name="history" size={16} />
            </button>
          </div>
          {/* 移动端抽屉切换 */}
          <div className="flex gap-1 md:hidden">
            <button
              onClick={() => setDrawer(drawer === 'path' ? null : 'path')}
              className="p-1.5 rounded-lg text-ink-dim hover:text-primary hover:bg-elevated transition-colors duration-150"
              aria-label="星图"
            >
              <Icon name="book" size={16} />
            </button>
            <button
              onClick={() => setDrawer(drawer === 'memory' ? null : 'memory')}
              className="p-1.5 rounded-lg text-ink-dim hover:text-primary hover:bg-elevated transition-colors duration-150"
              aria-label="星尘"
            >
              <Icon name="brain" size={16} />
            </button>
          </div>
        </div>
        <div className="flex items-center gap-2 text-[12px] text-ink-dim">
          <button
            onClick={() => setAuthOpen(true)}
            className="p-1.5 rounded-lg hover:text-primary hover:bg-elevated transition-colors duration-150"
            aria-label="接光"
            title="接光（API 连接令牌）"
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
          {debateVisible && <DebateView onClose={() => setDebateVisible(false)} onOpenLibrary={() => setSageLibOpen(true)} />}
          <ChatStream messages={messages} />
          <InputBar onOpenDebate={() => setDebateVisible((v) => !v)} sagesPending={sagesPending} />
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

      {/* Cmd+K 命令面板（2026-08-20 修复：onOpenPanel 需同时处理桌面左栏 + 移动端抽屉——之前只 setDrawer 桌面端不生效） */}
      <CommandPalette
        onOpenPanel={(p) => {
          setLeftOpen(true) // 桌面端：展开左栏
          useUiStore.getState().setPanelTab(p) // 切 PathPanel tab（受控）
          setDrawer(p) // 移动端：开抽屉
        }}
        onOpenDebate={() => {
          setDebateVisible(true)
        }}
      />

      {/* M6 通知横幅（双通道：页内 + 浏览器 Notification） */}
      <NotificationBanner />

      {/* 星阁管理窗（治理权六件套：列表/查看/确认/熄星/删观点/改元信息） */}
      <SageLibraryModal
        open={sageLibOpen}
        onClose={() => setSageLibOpen(false)}
        onRegistered={() => {
          /* 卡确认后：触发辩论视图刷新（待审徽标更新） */
          setDebateVisible(false)
        }}
      />

      {/* P0 门锁：接光令牌调光（手动按钮 / 401 自动弹出） */}
      <AuthModal open={authOpen} onOpenChange={setAuthOpen} />

      {/* B：夜谈记录抽屉（DeepSeek 式） */}
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
        onDelete={async (sid) => {
          await deleteSession(sid)
        }}
      />
    </div>
  )
}
