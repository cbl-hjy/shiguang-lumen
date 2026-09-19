/* 接光令牌调光入口（P0 门锁）：只由用户手动点"接光"按钮打开。
   2026-08-26 修正：401 不再自动弹窗——全屏弹窗会拦截星图等纯前端导航（用户实测"点星图没反应"），
   401 只通过顶栏"接光"按钮红点提示，用户需要时自己打开。 */
import { useState } from 'react'
import { getToken, setToken } from '../../api/auth'
import Icon from './Icon'

interface Props {
  open: boolean
  onOpenChange: (v: boolean) => void
}

export default function AuthModal({ open, onOpenChange }: Props) {
  const [value, setValue] = useState(getToken())

  const save = () => {
    setToken(value.trim())
    onOpenChange(false)
    // 2026-08-28 修复：不再 reload——fetch 包装运行时读 localStorage，令牌即时生效；
    // 原 reload 会整页刷新重放启动动画（用户"点保存弹启动动画"的根因）
  }

  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center"
      role="dialog"
      aria-modal="true"
    >
      <div
        className="absolute inset-0 bg-black/50"
        onClick={() => onOpenChange(false)}
        aria-label="关闭"
      />
      <div className="relative bg-bg border border-hairline rounded-xl p-5 w-80 shadow-2xl animate-msg-in">
        <div className="flex items-center gap-2 mb-1">
          <Icon name="wrench" size={14} />
          <h2 className="text-sm font-semibold text-primary">接光令牌</h2>
        </div>
        <p className="text-[12px] text-ink-dim mb-3">
          服务开启鉴权后需输入令牌（后端 .env 的 SHIGUANG_TOKEN），保存在本浏览器，下次免输。
        </p>
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="粘贴 SHIGUANG_TOKEN"
          autoFocus
          className="w-full bg-elevated border border-hairline rounded-lg px-3 py-2 text-sm text-primary outline-none focus:border-primary/40 mb-3"
        />
        <div className="flex gap-2 justify-end">
          <button
            onClick={() => onOpenChange(false)}
            className="px-3 py-1.5 rounded-lg text-sm text-ink-muted hover:text-primary"
          >
            取消
          </button>
          <button
            onClick={save}
            className="px-3 py-1.5 rounded-lg text-sm bg-primary/15 text-primary hover:bg-primary/25"
          >
            保存
          </button>
        </div>
      </div>
    </div>
  )
}
