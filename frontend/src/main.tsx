import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/tokens.css'
import App from './App.tsx'
import { installAuthFetch } from './api/auth'

installAuthFetch()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

/* 启动加载界面（2026-08-28 CSS 动画版：mascot 呼吸浮动+粒子+光晕，零加载延迟不依赖视频）：
   —— 只在 App【冷启动】播放一次（sessionStorage 标记；保存配置等页面内操作不再触发）
   2026-08-29 修复（用户实测"启动动画还没看到图就进主界面"）：
   原实现用固定 2.8s 定时器淡出——图片没加载完就被跳过（加载顺序在网络层，与计时器无关）。
   改为：图片 onload 完成 AND 最少展示 1.5s（动画完播）才淡出；3s 硬兜底防图片失败卡死启动。 */
const splash = document.getElementById('splash')
if (splash) {
  const SPLASH_KEY = 'shiguang_splash_shown'
  const MIN_MS = 1500 // 动画最少展示时长（完播）
  const MAX_MS = 3000 // 硬兜底：图片加载失败也不卡启动
  let shown = false
  try {
    shown = sessionStorage.getItem(SPLASH_KEY) === '1'
  } catch {
    /* 隐私模式忽略 */
  }

  if (shown) {
    splash.remove() // 同会话内（保存配置等）不再重放
  } else {
    try {
      sessionStorage.setItem(SPLASH_KEY, '1')
    } catch {
      /* 忽略 */
    }
    const start = performance.now()
    let imgDone = false
    let finished = false
    const img = splash.querySelector('img')
    if (img) {
      if (img.complete && img.naturalWidth > 0) {
        imgDone = true
      } else {
        img.addEventListener('load', () => {
          imgDone = true
          maybeFinish()
        })
        img.addEventListener('error', () => {
          imgDone = true // 加载失败也放行（兜底）
          maybeFinish()
        })
      }
    } else {
      imgDone = true
    }

    function maybeFinish(): void {
      if (finished) return
      if (!imgDone) return
      const elapsed = performance.now() - start
      if (elapsed < MIN_MS) {
        setTimeout(maybeFinish, MIN_MS - elapsed + 20)
        return
      }
      finished = true
      fadeOut()
    }

    function fadeOut(): void {
      if (!splash!.isConnected) return
      splash!.style.transition = 'opacity 0.5s ease'
      splash!.style.opacity = '0'
      setTimeout(() => splash!.remove(), 550)
    }

    maybeFinish()
    setTimeout(maybeFinish, MAX_MS) // 硬兜底
  }
}
