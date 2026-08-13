import { useEffect, useRef, useState } from 'react'

/* Mermaid 图渲染（表达自主：模型输出 ```mermaid 块 → 前端画图）
   lazy 加载（只有真出现 mermaid 块才引入库）+ dark 主题适配 + 失败降级为代码块 */
export default function MermaidRenderer({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [state, setState] = useState<'loading' | 'ok' | 'err'>('loading')
  const [errMsg, setErrMsg] = useState('')

  useEffect(() => {
    let cancelled = false
    const render = async () => {
      try {
        const mermaid = (await import('mermaid')).default
        mermaid.initialize({
          startOnLoad: false,
          theme: 'dark',
          themeVariables: {
            background: '#14171c',
            primaryColor: '#1d2730',
            primaryBorderColor: '#2d4048',
            primaryTextColor: '#e9e6dd',
            lineColor: '#4d5b63',
            fontFamily: '"LXGW WenKai", "JetBrains Mono", monospace',
          },
          securityLevel: 'loose',
        })
        const id = `mermaid-${Math.random().toString(36).slice(2, 9)}`
        const { svg } = await mermaid.render(id, code)
        if (!cancelled && ref.current) {
          ref.current.innerHTML = svg
          setState('ok')
        }
      } catch (e) {
        if (!cancelled) {
          setState('err')
          setErrMsg(e instanceof Error ? e.message : String(e))
        }
      }
    }
    render()
    return () => {
      cancelled = true
    }
  }, [code])

  if (state === 'err') {
    /* 渲染失败降级：保留代码块原文（模型语法错误也不崩） */
    return (
      <pre className="mb-2 p-3 rounded-lg bg-[#0d0f13] border border-hairline overflow-x-auto font-mono text-[13px] leading-[1.6]">
        <code>{code}</code>
        <div className="mt-2 text-[11px] text-[rgba(236,233,225,0.35)]">
          (图渲染失败{errMsg ? `：${errMsg.slice(0, 60)}` : ''}，已显示原始文本)
        </div>
      </pre>
    )
  }

  return (
    <div className="mb-2 rounded-lg bg-[#14171c] border border-hairline p-3 overflow-x-auto">
      <div ref={ref} className="mermaid-graph flex justify-center" />
      {state === 'loading' && (
        <div className="text-[12px] text-[rgba(236,233,225,0.4)] text-center py-4">绘制图中…</div>
      )}
    </div>
  )
}
