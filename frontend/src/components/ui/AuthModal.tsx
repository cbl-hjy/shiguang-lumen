/* 连接令牌设置入口（P0 门锁）：设置按钮手动打开 / 401 自动弹出。
   手机局域网访问时输入一次（localStorage 持久），保存后刷新使所有请求带 token。 */
import { useEffect, useState } from 'react'
import { getToken, setToken, AUTH_REQUIRED_EVENT } from '../../api/auth'
import Icon from './Icon'

interface Props {
  open: boolean
  onOpenChange: (v: boolean) => void
}

export default function AuthModal({ open, onOpenChange }: Props) {
  const [value, setValue] = useState(getToken())

  useEffect(() => {
    const onAuth = () => onOpenChange(true)
    window.addEventListener(AUTH_REQUIRED_EVENT, onAuth)
    return () => window.removeEventListener(AUTH_REQUIRED_EVENT, onAuth)
  }, [onOpenChange])

  const save = () => {
    setToken(value.trim())
    onOpenChange(false)
    window.location.reload()
  }

  if (!open) return null
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/50" onClick={() => onOpenChange(false)} aria-label="关闭" />
      <div className="relative bg-bg border border-hairline rounded-xl p-5 w-80 shadow-2xl animate-msg-in">
        <div className="flex items-center gap-2 mb-1">
          <Icon name="wrench" size={14} />
          <h2 className="text-sm font-semibold text-primary">连接令牌</h2>
        </div>
        <p className="text-[12px] text-[rgba(236,233,225,0.55)] mb-3">
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
            className="px-3 py-1.5 rounded-lg text-sm text-[rgba(236,233,225,0.6)] hover:text-primary"
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
