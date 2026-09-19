/* 登录 / 注册页（2026-08-28 P3 多用户账号体系 + 2026-08-28 服务器地址前置）：
   - 登录：邮箱 + 密码；注册：昵称 + 邮箱 + 密码 + 确认（首个注册用户=管理员）
   - 服务器地址：APK 环境（appassets origin）或未配置时，顶部必填服务器地址——
     注册/登录请求都发往该服务器；桌面同源无需填写
   - 成功后存 JWT + 用户信息，回调 onAuthed() 进入主界面
   - 忘记密码：联系管理员（PC 端 scripts/reset_password.py）重置 */
import { useState } from 'react'
import { apiLogin, apiRegister, getApiBase, setApiBase } from '../../api/auth'

/* APK 内嵌 WebView：origin 是 appassets.androidplatform.net，相对 /api 打不到后端，
   必须配置服务器地址（http://IP:8000 或 Tailscale IP）。桌面同源无需配置。 */
function isAppShell(): boolean {
  try {
    return location.origin.startsWith('appassets') || location.protocol === 'file:'
  } catch {
    return true
  }
}

export default function AuthPage({ onAuthed }: { onAuthed: () => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [nickname, setNickname] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [invite, setInvite] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const needAddr = isAppShell() || !getApiBase()
  const [addr, setAddr] = useState(getApiBase())

  const submit = async () => {
    setErr('')
    if (needAddr && !addr.trim()) {
      setErr('请先填写服务器地址（电脑 IP 或 Tailscale 地址）')
      return
    }
    if (!email.trim() || !password) {
      setErr('请填写邮箱和密码')
      return
    }
    if (mode === 'register') {
      if (!nickname.trim()) return setErr('请填写昵称')
      if (!invite.trim()) return setErr('请填写邀请码（管理员提供）')
      if (password.length < 8) return setErr('密码至少 8 位')
      if (password !== confirm) return setErr('两次密码不一致')
    }
    setBusy(true)
    // 提交时临时生效用户输入的地址（请求发往它）；失败后回滚——错误地址不持久化
    const prevBase = getApiBase()
    if (addr.trim() && addr.trim() !== prevBase) setApiBase(addr.trim())
    try {
      if (mode === 'login') await apiLogin(email.trim(), password)
      else await apiRegister(nickname.trim(), email.trim(), password, invite.trim())
      onAuthed()
    } catch (e) {
      // 2026-08-29 死锁修复：失败回滚地址（防错误地址持久化 → 输入框消失）；
      // 输入框无条件显示（上方渲染），可随时修改重试
      if (getApiBase() !== prevBase) setApiBase(prevBase)
      const isAbort = e instanceof Error && e.name === 'AbortError'
      const msg = e instanceof Error ? e.message : '操作失败，请重试'
      // AbortError（12s 连接超时）与 fetch/network 错误都归入"服务器连不上"——友好中文提示
      setErr(
        isAbort || (/fetch|network|Failed/i.test(msg) && needAddr)
          ? `无法连接到服务器（${isAbort ? '连接超时' : '请检查服务器地址'}：${addr || '未填写'}）`
          : msg,
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-[90] flex items-center justify-center p-6 overflow-y-auto"
      style={{
        background: 'radial-gradient(120% 90% at 50% 10%, #131a2e 0%, #0d0f13 55%, #080a0e 100%)',
      }}
    >
      <div className="w-full max-w-sm my-auto">
        {/* mascot 占位 + 品牌 */}
        <div className="flex flex-col items-center mb-6">
          <img
            src="./splash-mascot.png"
            alt="拾光"
            className="w-24 h-24 rounded-2xl mb-4 shadow-[0_0_40px_rgba(62,201,176,0.3)]"
          />
          <h1 className="text-[22px] font-medium tracking-[8px] text-[#ece9e1] text-indent-[8px]">
            拾光 Lumen
          </h1>
          <p className="mt-2 text-[12px] tracking-[3px] text-[#8b93a3]">你的成长搭子</p>
        </div>

        <div className="rounded-2xl border border-hairline bg-elevated p-5">
          {/* 服务器地址（2026-08-29 死锁修复：始终显示——即使已配置也保留可改入口；
              输错地址失败后不持久化，输入框不会消失） */}
          <input
            value={addr}
            onChange={(e) => setAddr(e.target.value)}
            placeholder={
              isAppShell()
                ? '服务器地址，如 http://<lan-ip>:8000'
                : addr
                  ? `服务器地址（当前：${addr}，可修改）`
                  : '服务器地址（可选，如 http://<lan-ip>:8000）'
            }
            inputMode="url"
            className="w-full rounded-lg border border-ink/30 bg-surface px-3 py-2.5 text-[13px] text-ink outline-none focus:border-primary/60 mb-2.5 transition-colors duration-150"
          />
          <p className="text-[11px] text-ink-dim mb-3 leading-relaxed">
            首次使用需填写电脑的服务器地址（管理员会告诉你；同一 WiFi 下，或 Tailscale 地址）
          </p>

          <div className="flex gap-2 mb-4">
            {(['login', 'register'] as const).map((m) => (
              <button
                key={m}
                onClick={() => {
                  setMode(m)
                  setErr('')
                }}
                className={`flex-1 py-1.5 rounded-lg text-[13px] transition-colors duration-150 ${
                  mode === m ? 'bg-primary/15 text-primary' : 'text-ink-dim hover:text-ink'
                }`}
              >
                {m === 'login' ? '登录' : '注册'}
              </button>
            ))}
          </div>

          {mode === 'register' && (
            <input
              value={nickname}
              onChange={(e) => setNickname(e.target.value)}
              placeholder="昵称（别人看到的名字）"
              className="w-full rounded-lg border border-ink/30 bg-surface px-3 py-2.5 text-[13px] text-ink outline-none focus:border-primary/60 mb-2.5 transition-colors duration-150"
            />
          )}
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="邮箱（登录凭据）"
            type="email"
            className="w-full rounded-lg border border-ink/30 bg-surface px-3 py-2.5 text-[13px] text-ink outline-none focus:border-primary/60 mb-2.5 transition-colors duration-150"
          />
          <input
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="密码（至少 8 位）"
            type="password"
            className="w-full rounded-lg border border-ink/30 bg-surface px-3 py-2.5 text-[13px] text-ink outline-none focus:border-primary/60 mb-2.5 transition-colors duration-150"
          />
          {mode === 'register' && (
            <>
              <input
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                placeholder="确认密码"
                type="password"
                className="w-full rounded-lg border border-ink/30 bg-surface px-3 py-2.5 text-[13px] text-ink outline-none focus:border-primary/60 mb-2.5 transition-colors duration-150"
              />
              <input
                value={invite}
                onChange={(e) => setInvite(e.target.value)}
                placeholder="邀请码（找管理员要）"
                className="w-full rounded-lg border border-ink/30 bg-surface px-3 py-2.5 text-[13px] text-ink outline-none focus:border-primary/60 mb-2.5 transition-colors duration-150"
              />
            </>
          )}

          {err && <p className="text-[12px] text-error mb-2">{err}</p>}

          <button
            onClick={submit}
            disabled={busy}
            className="w-full py-2.5 rounded-lg bg-primary text-primary-ink text-[14px] font-medium hover:opacity-90 active:scale-[0.98] transition-all duration-150 disabled:opacity-50"
          >
            {busy ? '请稍候…' : mode === 'login' ? '登 录' : '注册并进入'}
          </button>

          <p className="mt-3 text-[11px] text-ink-dim leading-relaxed">
            {mode === 'login'
              ? '忘记密码？联系管理员在电脑端重置（scripts/reset_password.py）'
              : '注册需要邀请码（管理员提供）；首个注册的用户是管理员'}
          </p>
        </div>
      </div>
    </div>
  )
}
