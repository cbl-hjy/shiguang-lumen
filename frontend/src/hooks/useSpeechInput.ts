/* 语音输入封装（2026-08-29）：Web Speech API（SpeechRecognition/webkitSpeechRecognition）。
   调研结论：Chrome 语音走 Google 服务器（国内不可用）；Edge 走 Azure（本机可用性待实测）；
   本封装做支持检测 + 错误映射，不支持的浏览器诚实降级（提示而非假装可用）。
   Vosk 离线 WASM（40MB 模型）为挂账方案——模型下载被墙风险高，暂不引入。 */

export function speechSupported(): boolean {
  try {
    const W = window as unknown as Record<string, unknown>
    return typeof window !== 'undefined' && !!(W.SpeechRecognition || W.webkitSpeechRecognition)
  } catch {
    return false
  }
}

export interface SpeechHandlers {
  onInterim: (text: string) => void
  onFinal: (text: string) => void
  onEnd: () => void
  onError: (msg: string) => void
}

export interface SpeechController {
  start: () => void
  stop: () => void
}

type SpeechResult = { isFinal: boolean; transcript: string }
type SpeechEvent = { results: ArrayLike<SpeechResult>; resultIndex: number }

type RecLike = {
  lang: string
  continuous: boolean
  interimResults: boolean
  maxAlternatives: number
  start: () => void
  stop: () => void
  abort: () => void
  onresult: ((e: SpeechEvent) => void) | null
  onerror: ((e: { error: string }) => void) | null
  onend: (() => void) | null
}

export function createSpeechRecognition(handlers: SpeechHandlers): SpeechController | null {
  if (!speechSupported()) return null
  const W = window as unknown as Record<string, unknown>
  const Ctor = (W.SpeechRecognition || W.webkitSpeechRecognition) as new () => RecLike
  const rec = new Ctor()
  rec.lang = 'zh-CN'
  rec.continuous = true
  rec.interimResults = true
  rec.maxAlternatives = 1

  rec.onresult = (e) => {
    let interim = ''
    let final = ''
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i]
      if (r.isFinal) final += r.transcript
      else interim += r.transcript
    }
    if (final) handlers.onFinal(final)
    else if (interim) handlers.onInterim(interim)
  }
  rec.onerror = (e) => {
    const map: Record<string, string> = {
      'not-allowed': '麦克风权限被拒绝——请在浏览器地址栏左侧允许麦克风后重试',
      'no-speech': '没有听到声音，请靠近麦克风再说一次',
      'network': '语音识别服务不可用（浏览器语音服务需要网络，国内部分浏览器可能连不上）',
      'service-not-allowed': '语音服务被浏览器禁用',
      'audio-capture': '没有检测到麦克风设备',
    }
    handlers.onError(map[e.error] || `语音识别出错（${e.error}）`)
  }
  rec.onend = () => handlers.onEnd()

  return {
    start: () => {
      try {
        rec.start()
      } catch {
        /* 已启动时重复 start 会抛错，忽略 */
      }
    },
    stop: () => {
      try {
        rec.stop()
      } catch {
        /* 忽略 */
      }
    },
  }
}
