import { useState } from 'react'
import type { MemoryEntry } from '../../api/memory'
import DetailModal from '../ui/DetailModal'
import Icon from '../ui/Icon'

const CAT_TAG: Record<string, string> = {
  preference: '偏好',
  goal: '目标',
  progress: '进度',
  learning: '学习',
  mistake: '错误',
  note: '笔记',
  闪光: '闪光',
  困惑: '困惑',
}

function CategoryPill({ category }: { category: string }) {
  return (
    <span className="px-1.5 py-0.5 rounded-md bg-primary/10 text-primary text-[10px]">
      {CAT_TAG[category] ?? category}
    </span>
  )
}

/* 星尘卡片：摘要行（只做入口）→ 点击弹中央 modal（14px 全文 + 修正 6 行 textarea + 熄星）
   破坏性操作只留一个刻意入口（回顾场景，慢一点是特性）；hover 熄星移除（防 12px 误删） */
export default function MemoryCard({
  entry,
  onEdited,
  onDeleted,
}: {
  entry: MemoryEntry
  onEdited: (old: string, newText: string) => void
  onDeleted: (content: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(entry.content)

  return (
    <>
      <button
        onClick={() => {
          setDraft(entry.content)
          setEditing(false)
          setOpen(true)
        }}
        className="group w-full text-left rounded-lg border border-hairline bg-surface p-2.5 hover:bg-elevated transition-colors duration-150 cursor-pointer"
        aria-label={`查看星尘：${entry.content.slice(0, 20)}`}
      >
        <div className="flex items-center gap-1.5 mb-1">
          <CategoryPill category={entry.category} />
          {entry.importance >= 8 && <span className="text-[10px] text-warning">★</span>}
          {/* S 强度（治理权，2026-08-19）：被检索用过 N 次 = strength-1；S=1 不显示（没被用过） */}
          {entry.strength && entry.strength > 1 && (
            <span className="text-[10px] text-primary/70" title="这条星尘被检索使用过的次数（用进废退 S+1）">
              用过 {entry.strength - 1} 次
            </span>
          )}
          <span className="text-[10px] text-ink-dim/70 ml-auto">{entry.date}</span>
        </div>
        <div className="text-[12px] leading-relaxed text-ink/85 line-clamp-2">
          {entry.content}
        </div>
      </button>

      <DetailModal
        title={`星尘 · ${CAT_TAG[entry.category] ?? entry.category}`}
        open={open}
        onClose={() => setOpen(false)}
        footer={
          editing ? (
            <>
              <button
                onClick={() => setEditing(false)}
                className="text-[12px] text-ink-dim hover:text-ink/85 transition-colors"
              >
                取消
              </button>
              <button
                onClick={() => {
                  onEdited(entry.content, draft)
                  setEditing(false)
                  setOpen(false)
                }}
                className="text-[12px] text-primary hover:opacity-80 transition-opacity"
              >
                保存
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => setEditing(true)}
                className="flex items-center gap-1 text-[12px] text-ink-muted hover:text-primary transition-colors"
              >
                <Icon name="wrench" size={12} />
                修正
              </button>
              <button
                onClick={() => {
                  onDeleted(entry.content)
                  setOpen(false)
                }}
                className="flex items-center gap-1 text-[12px] text-ink-muted hover:text-error transition-colors"
              >
                <Icon name="trash" size={12} />
                熄星
              </button>
            </>
          )
        }
      >
        {editing ? (
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={6}
            className="w-full bg-transparent text-[14px] outline-none resize-none text-ink"
            autoFocus
          />
        ) : (
          <>
            <div className="text-[12px] text-ink-dim/80 mb-2">
              {entry.date} · 重要度 {entry.importance} · 来源 {entry.source}
            </div>
            {entry.content}
          </>
        )}
      </DetailModal>
    </>
  )
}
