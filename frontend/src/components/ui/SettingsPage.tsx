/* 设置页（2026-08-28 产品化整改——用户点名缺"设置"）：
   账号 / 外观（内置主题切换）/ 服务器 / 数据 / 关于 + 退出登录（二次确认，提示数据保留）。
   对齐 iOS HUD / Material：信息分组、低风险操作直接生效、高风险（退出）必须确认。 */
import { useRef, useState } from 'react'
import Icon from './Icon'
import { getApiBase, setApiBase, logout, updateAvatar, type UserInfo } from '../../api/auth'
import { getTheme, applyTheme, THEMES, type ThemeId } from '../../lib/theme'
import { getCustomBg, setCustomBg, clearCustomBg } from '../../lib/theme'

interface Props {
  user: UserInfo | null
  onClose: () => void
  onLogout: () => void
  onOpenStarMap?: () => void // 全部功能（星图：知识库/议会/用量/观测/记忆管理）
}

export default function SettingsPage({ user, onClose, onLogout, onOpenStarMap }: Props) {
  const [theme, setTheme] = useState<ThemeId>(getTheme())
  const [apiBase, setBase] = useState(getApiBase())
  const [baseSaved, setBaseSaved] = useState(false)
  const [confirmExit, setConfirmExit] = useState(false)
  // 2026-08-29 头像：本地 state（user 是外部只读 props，更新后本地回填）
  const [avatar, setAvatar] = useState(user?.avatar || '')
  const [avatarBusy, setAvatarBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  // 2026-08-29 自定义背景：localStorage 存储（设置页改完即时生效）
  const [bg, setBg] = useState(getCustomBg())
  const [bgBusy, setBgBusy] = useState(false)
  const bgRef = useRef<HTMLInputElement>(null)

  const pickBg = async (file: File) => {
    if (!file.type.startsWith('image/')) return
    setBgBusy(true)
    try {
      // canvas 压缩到 1920 宽（JPEG 0.8 → base64 ≈ 300-500KB，localStorage 友好）
      const bmp = await createImageBitmap(file)
      const maxW = 1920
      const scale = Math.min(1, maxW / bmp.width)
      const canvas = document.createElement('canvas')
      canvas.width = Math.round(bmp.width * scale)
      canvas.height = Math.round(bmp.height * scale)
      const ctx = canvas.getContext('2d')
      if (!ctx) throw new Error('canvas 不可用')
      ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height)
      const b64 = canvas.toDataURL('image/jpeg', 0.8)
      setCustomBg(b64)
      setBg(b64)
    } catch (e) {
      alert('背景上传失败：' + (e instanceof Error ? e.message : '未知错误'))
    } finally {
      setBgBusy(false)
    }
  }

  const pickTheme = (t: ThemeId) => {
    setTheme(t)
    applyTheme(t)
  }

  const pickAvatar = async (file: File) => {
    if (!file.type.startsWith('image/')) return
    setAvatarBusy(true)
    try {
      // canvas 压缩到 128px（头像小图 ≈15KB base64，DB 存储友好）
      const bmp = await createImageBitmap(file)
      const size = 128
      const canvas = document.createElement('canvas')
      canvas.width = size
      canvas.height = size
      const ctx = canvas.getContext('2d')
      if (!ctx) throw new Error('canvas 不可用')
      const side = Math.min(bmp.width, bmp.height)
      ctx.drawImage(
        bmp,
        (bmp.width - side) / 2,
        (bmp.height - side) / 2,
        side,
        side,
        0,
        0,
        size,
        size,
      )
      const dataUrl = canvas.toDataURL('image/jpeg', 0.85)
      const u = await updateAvatar(dataUrl)
      setAvatar(u.avatar || '')
    } catch (e) {
      alert('头像上传失败：' + (e instanceof Error ? e.message : '未知错误'))
    } finally {
      setAvatarBusy(false)
    }
  }

  const saveBase = () => {
    const v = apiBase.trim().replace(/\/+$/, '') // 去尾部斜杠
    setApiBase(v)
    setBase(v)
    setBaseSaved(true)
    setTimeout(() => setBaseSaved(false), 1600)
  }

  const doLogout = () => {
    logout()
    onLogout()
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-elevated/95 backdrop-blur-md animate-panel-in">
      {/* 顶栏 */}
      <header className="flex items-center gap-3 px-4 py-3 border-b border-hairline shrink-0" style={{ paddingTop: 'max(env(safe-area-inset-top), 12px)' }}>
        <button
          onClick={onClose}
          className="p-2 -ml-2 rounded-lg text-ink-muted hover:text-ink hover:bg-surface transition-colors duration-150"
          aria-label="关闭设置"
        >
          <Icon name='x' size={18} />
        </button>
        <h1 className="text-[15px] font-medium text-ink">设置</h1>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-5">
        {/* 账号 */}
        <section>
          <p className="text-[11px] text-ink-dim mb-2 flex items-center gap-1">
            <Icon name='user' size={11} /> 账号
          </p>
          <div className="rounded-xl border border-hairline bg-surface/60 divide-y divide-hairline/50">
            {/* 头像（2026-08-29）：上传 128px 小图，DB 持久化跨设备同步 */}
            <div className="flex items-center justify-between px-3.5 py-3">
              <span className="text-[13px] text-ink-dim">头像</span>
              <div className="flex items-center gap-2">
                {avatar ? (
                  <img src={avatar} alt="头像" className="w-8 h-8 rounded-full object-cover border border-hairline" />
                ) : (
                  <span className="w-8 h-8 rounded-full bg-elevated border border-hairline flex items-center justify-center text-[12px] text-ink-dim">
                    {(user?.nickname || '?').slice(0, 1)}
                  </span>
                )}
                <button
                  onClick={() => fileRef.current?.click()}
                  disabled={avatarBusy}
                  className="text-[11px] px-2.5 py-1.5 rounded-lg border border-hairline hover:border-amber/50 text-ink-dim hover:text-ink transition-colors duration-150 disabled:opacity-50"
                >
                  {avatarBusy ? '处理中…' : avatar ? '更换' : '上传'}
                </button>
                {avatar && (
                  <button
                    onClick={async () => {
                      try {
                        await updateAvatar('')
                        setAvatar('')
                      } catch {
                        /* 清除失败静默（下次重试） */
                      }
                    }}
                    className="text-[11px] px-2.5 py-1.5 rounded-lg border border-hairline text-ink-dim hover:text-red/80 hover:border-red/40 transition-colors duration-150"
                  >
                    移除
                  </button>
                )}
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    if (f) pickAvatar(f)
                    e.target.value = ''
                  }}
                />
              </div>
            </div>
            <div className="flex items-center justify-between px-3.5 py-3">
              <span className="text-[13px] text-ink-dim">昵称</span>
              <span className="text-[13px] text-ink">{user?.nickname || '—'}</span>
            </div>
            <div className="flex items-center justify-between px-3.5 py-3">
              <span className="text-[13px] text-ink-dim">邮箱</span>
              <span className="text-[13px] text-ink font-mono text-[12px]">{user?.email || '—'}</span>
            </div>
            <div className="flex items-center justify-between px-3.5 py-3">
              <span className="text-[13px] text-ink-dim">身份</span>
              <span className={`text-[11px] px-2 py-0.5 rounded-full border ${user?.is_admin ? 'border-amber/40 text-amber' : 'border-hairline text-ink-dim'}`}>
                {user?.is_admin ? '管理员' : '普通成员'}
              </span>
            </div>
          </div>
        </section>

        {/* 外观：内置主题切换 */}
        <section>
          <p className="text-[11px] text-ink-dim mb-2 flex items-center gap-1">
            <Icon name='palette' size={11} /> 外观 · 背景
          </p>
          <div className="grid grid-cols-3 gap-2">
            {THEMES.map((t) => (
              <button
                key={t.id}
                onClick={() => pickTheme(t.id)}
                className={`rounded-xl border p-2.5 text-left transition-all duration-150 ${
                  theme === t.id
                    ? 'border-primary/60 bg-primary/10 shadow-[0_0_16px_rgba(62,201,176,0.15)]'
                    : 'border-hairline bg-surface/60 hover:border-ink/40'
                }`}
                aria-pressed={theme === t.id}
              >
                {/* 主题色卡 */}
                <span className="block h-8 rounded-lg mb-2" style={{ background: `linear-gradient(120deg, ${t.swatch[0]}, ${t.swatch[2]})` }} />
                <span className="flex items-center gap-1 text-[12px] text-ink">
                  {t.name}
                  {theme === t.id && <Icon name='check' size={12} className='text-primary' />}
                </span>
                <span className="block text-[10px] text-ink-dim mt-0.5 leading-snug">{t.desc}</span>
              </button>
            ))}
          </div>

          {/* 自定义背景（2026-08-29）：上传图铺底（压缩 1920 宽存 localStorage） */}
          <div className="mt-2.5 rounded-xl border border-hairline bg-surface/60 px-3.5 py-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {bg ? (
                  <span className="w-10 h-7 rounded-md border border-hairline bg-cover bg-center" style={{ backgroundImage: `url(${bg})` }} />
                ) : (
                  <span className="w-10 h-7 rounded-md border border-hairline flex items-center justify-center text-[10px] text-ink-dim">无</span>
                )}
                <div>
                  <p className="text-[12px] text-ink">自定义背景</p>
                  <p className="text-[10px] text-ink-dim leading-snug">上传你的图片当背景（会加暗化遮罩保证文字可读）</p>
                </div>
              </div>
              <div className="flex items-center gap-1.5">
                <button
                  onClick={() => bgRef.current?.click()}
                  disabled={bgBusy}
                  className="text-[11px] px-2.5 py-1.5 rounded-lg border border-hairline hover:border-amber/50 text-ink-dim hover:text-ink transition-colors duration-150 disabled:opacity-50"
                >
                  {bgBusy ? '处理中…' : bg ? '更换' : '上传'}
                </button>
                {bg && (
                  <button
                    onClick={() => {
                      clearCustomBg()
                      setBg('')
                    }}
                    className="text-[11px] px-2.5 py-1.5 rounded-lg border border-hairline text-ink-dim hover:text-red/80 hover:border-red/40 transition-colors duration-150"
                  >
                    移除
                  </button>
                )}
                <input
                  ref={bgRef}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    if (f) pickBg(f)
                    e.target.value = ''
                  }}
                />
              </div>
            </div>
          </div>
        </section>

        {/* 服务器 */}
        <section>
          <p className="text-[11px] text-ink-dim mb-2 flex items-center gap-1">
            <Icon name='server' size={11} /> 服务器
          </p>
          <div className="rounded-xl border border-hairline bg-surface/60 p-3.5">
            <div className="flex gap-2">
              <input
                value={apiBase}
                onChange={(e) => setBase(e.target.value)}
                placeholder="http://192.168.x.x:8000"
                className="flex-1 min-w-0 rounded-lg border border-ink/30 bg-elevated px-3 py-2 text-[13px] text-ink outline-none focus:border-primary/60 transition-colors duration-150"
                aria-label="服务器地址"
              />
              <button
                onClick={saveBase}
                className={`shrink-0 px-3.5 py-2 rounded-lg text-[13px] transition-all duration-150 active:scale-95 ${
                  baseSaved ? 'bg-primary/20 text-primary' : 'bg-primary text-primary-ink'
                }`}
              >
                {baseSaved ? '已保存' : '保存'}
              </button>
            </div>
            <p className="text-[11px] text-ink-dim mt-2 leading-relaxed">
              手机 App 连电脑后端用。同一 WiFi 填电脑 IP（如 http://<lan-ip>:8000）；
              远程使用填 Tailscale 或公网地址。保存后立即生效。
            </p>
          </div>
        </section>

        {/* 数据 */}
        <section>
          <p className="text-[11px] text-ink-dim mb-2 flex items-center gap-1">
            <Icon name='database' size={11} /> 数据与隐私
          </p>
          <div className="rounded-xl border border-hairline bg-surface/60 px-3.5 py-3">
            <p className="text-[12px] text-ink/90 leading-relaxed">
              你的对话、记忆、画像都存放在<strong className="text-ink">你自己的独立空间</strong>（本地/你的服务端），
              与其他人完全隔离。记忆可在「星图 → 记忆管理」中查看、修正、删除（删除进回收站可恢复）。
            </p>
          </div>
        </section>

        {/* 全部功能（星图：低频，降级入口） */}
        {onOpenStarMap && (
          <section>
            <p className="text-[11px] text-ink-dim mb-2 flex items-center gap-1">
              <Icon name='grid' size={11} /> 全部功能
            </p>
            <button
              onClick={onOpenStarMap}
              className="w-full flex items-center justify-between px-3.5 py-3 rounded-xl border border-hairline bg-surface/60 hover:border-ink/40 active:scale-95 transition-all duration-150"
            >
              <span className="text-[13px] text-ink">星图 · 高级功能</span>
              <span className="flex items-center gap-1 text-[11px] text-ink-dim">
                知识库 · 议会 · 用量 · 观测 <Icon name='chevron-right' size={12} />
              </span>
            </button>
          </section>
        )}

        {/* 关于 */}
        <section>
          <p className="text-[11px] text-ink-dim mb-2 flex items-center gap-1">
            <Icon name='info' size={11} /> 关于
          </p>
          <div className="rounded-xl border border-hairline bg-surface/60 divide-y divide-hairline/50">
            <div className="flex items-center justify-between px-3.5 py-3">
              <span className="text-[13px] text-ink-dim">版本</span>
              <span className="text-[13px] text-ink flex items-center gap-1">
                v1.1.3 <Icon name='chevron-right' size={12} className='text-ink-dim' />
              </span>
            </div>
            <div className="px-3.5 py-3">
              <p className="text-[12px] text-ink/90 leading-relaxed">
                拾光 Lumen——本地优先的 AI 成长搭子。你的记忆只属于你，
                它陪你越聊越懂你。
              </p>
            </div>
          </div>
        </section>

        {/* 退出（二次确认） */}
        <section>
          {confirmExit ? (
            <div className="rounded-xl border border-error/40 bg-error/8 p-4 animate-toast-in">
              <p className="text-[13px] text-ink leading-relaxed mb-3">
                退出后需要重新登录。<strong className="text-ink">你的记忆、会话数据会保留</strong>，
                重新登录后原样回来。
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => setConfirmExit(false)}
                  className="flex-1 py-2.5 rounded-lg border border-hairline text-[13px] text-ink-muted hover:text-ink hover:bg-surface transition-colors duration-150"
                >
                  取消
                </button>
                <button
                  onClick={doLogout}
                  className="flex-1 py-2.5 rounded-lg bg-error/90 text-white text-[13px] hover:bg-error active:scale-95 transition-all duration-150"
                >
                  退出登录
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setConfirmExit(true)}
              className="w-full flex items-center justify-center gap-2 py-3 rounded-xl border border-error/30 text-error text-[13px] hover:bg-error/10 active:scale-95 transition-all duration-150"
            >
              <Icon name='logout' size={14} /> 退出登录
            </button>
          )}
        </section>
      </div>
    </div>
  )
}
