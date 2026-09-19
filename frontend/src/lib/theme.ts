/* 主题切换（2026-08-28 设置页）：data-theme 属性 + localStorage 持久化。
   三套内置主题：starry(星空·默认) / deepspace(深空·极简) / ember(暖光·琥珀) */
export type ThemeId = 'starry' | 'deepspace' | 'ember'

export const THEMES: { id: ThemeId; name: string; desc: string; swatch: string[] }[] = [
  { id: 'starry', name: '星空', desc: '深蓝夜空 · 极光漂移（默认）', swatch: ['#141b29', '#3ec9b0', '#8f6bff'] },
  { id: 'deepspace', name: '深空', desc: '纯黑极简 · 极光压暗，专注阅读', swatch: ['#0a0c10', '#1a2a3a', '#3ec9b0'] },
  { id: 'ember', name: '暖光', desc: '琥珀暖调 · 光的家的氛围', swatch: ['#1d150c', '#e6be78', '#be5428'] },
]

const KEY = 'shiguang_theme'

export function getTheme(): ThemeId {
  try {
    const v = localStorage.getItem(KEY)
    if (v === 'starry' || v === 'deepspace' || v === 'ember') return v
  } catch {
    /* ignore */
  }
  return 'starry'
}

export function applyTheme(t: ThemeId) {
  try {
    localStorage.setItem(KEY, t)
  } catch {
    /* ignore */
  }
  const body = document.body
  if (t === 'starry') body.removeAttribute('data-theme')
  else body.setAttribute('data-theme', t)
}

export function initTheme() {
  applyTheme(getTheme())
}

/* ===== 自定义背景（2026-08-29）：localStorage 存压缩 JPEG base64（1920 宽 ≈ 300-500KB）===== */
const BG_KEY = 'shiguang_custom_bg'

export function getCustomBg(): string {
  try {
    return localStorage.getItem(BG_KEY) || ''
  } catch {
    return ''
  }
}

export function setCustomBg(b64: string): void {
  try {
    if (b64) localStorage.setItem(BG_KEY, b64)
    else localStorage.removeItem(BG_KEY)
  } catch {
    /* 忽略（存储满等） */
  }
}

export function clearCustomBg(): void {
  setCustomBg('')
}
