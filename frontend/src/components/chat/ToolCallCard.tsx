import Icon from '../ui/Icon'
import type { ToolCall } from '../../types/chat'

const TOOL_ICON: Record<string, 'search' | 'code' | 'image' | 'file' | 'book' | 'download' | 'brain' | 'user' | 'trash' | 'wrench'> = {
  web_search: 'search',
  python_sandbox: 'code',
  ocr_image: 'image',
  read_document: 'file',
  kb_search: 'book',
  kb_ingest: 'download',
  remember: 'brain',
  search_memory: 'search',
  update_profile: 'user',
  forget: 'trash',
}

/* 工具调用卡片：模型自主调用工具的实时可视化（Cursor 范式，线性图标） */
function argsSummary(raw?: string): string {
  if (!raw) return ''
  let s = raw.trim()
  if (s.startsWith('{') || s.startsWith('[')) {
    try {
      const v = JSON.parse(s)
      const first = Array.isArray(v) ? v[0] : Object.values(v)[0]
      if (typeof first === 'string') s = first
    } catch {
      /* 非严格 JSON，原样处理 */
    }
  }
  s = s.replace(/[{}"\[\]]/g, ' ').replace(/\s+/g, ' ').trim()
  return s.length > 40 ? s.slice(0, 40) + '…' : s
}

export default function ToolCallCard({ call }: { call: ToolCall }) {
  const done = call.status === 'done'
  const args = argsSummary(call.args)
  return (
    <div
      className={`inline-flex items-center gap-1.5 mb-1.5 mr-2 px-2.5 py-1 rounded-lg border border-hairline bg-surface text-[12px] ${
        done ? 'animate-tool-done' : ''
      }`}
    >
      <Icon name={TOOL_ICON[call.name] ?? 'wrench'} size={13} className="text-[rgba(236,233,225,0.6)]" />
      <span className="text-[rgba(236,233,225,0.75)]">{call.name}</span>
      {!done && args && (
        <span className="text-[rgba(236,233,225,0.4)] max-w-[220px] truncate" title={args}>
          {args}
        </span>
      )}
      {done ? (
        <Icon name="check" size={12} className="text-success" />
      ) : (
        <span className="text-[rgba(236,233,225,0.35)]">…</span>
      )}
    </div>
  )
}
