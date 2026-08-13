import { useEffect, useState } from 'react'
import { fetchMemory, fetchProgress } from '../../api'
import Icon from '../ui/Icon'

/* 空状态欢迎语：从真实画像/目标拼接（非模板）——"我记得你在学正则化" */
export default function Welcome() {
  const [line, setLine] = useState('想学什么，直接说——拾光记得你的每一步')

  useEffect(() => {
    Promise.all([fetchMemory(), fetchProgress()])
      .then(([mem, prog]) => {
        if (prog.topics.length > 0) {
          setLine(`我记得你在学「${prog.topics[0].title}」，今天想学点什么？`)
        } else if (mem.profile && mem.profile.length > 8) {
          const first = mem.profile.replace(/^用户/, '').slice(0, 24)
          setLine(`我记得你${first}…今天想学点什么？`)
        }
      })
      .catch(() => undefined)
  }, [])

  return (
    <div className="flex-1 flex items-center justify-center p-6">
      <div className="text-center">
        {/* "拾光"点亮动画：一次性光晕扩散（仪式感，非循环） */}
        <p className="font-logo text-3xl text-primary tracking-[0.08em] animate-welcome-light">拾光</p>
        <p className="mt-3 text-[13px] text-[rgba(236,233,225,0.45)] max-w-[320px] mx-auto leading-relaxed">
          {line}
        </p>
        <p className="mt-4 flex items-center justify-center gap-1.5 text-[11px] text-[rgba(236,233,225,0.3)]">
          <Icon name="brain" size={13} />
          记忆 · 工具 · 学习路径 已就绪
        </p>
      </div>
    </div>
  )
}
