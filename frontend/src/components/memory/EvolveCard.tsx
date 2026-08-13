import { useState } from 'react'
import { deleteEvolutionItem, type EvolveItem } from '../../api/memory'
import DetailModal from '../ui/DetailModal'
import Icon from '../ui/Icon'

/* 反思/技能条目卡：一行（类型+日期，只做入口）→ 点击弹中央 modal（14px 只读全文 + 删除）
   破坏性操作只留一个刻意入口；accordion 移除（长内容 modal 内滚动才读得全） */
export default function EvolveCard({
  item,
  kind,
  onDeleted,
}: {
  item: EvolveItem
  kind: 'reflection' | 'skill'
  onDeleted: (content: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const isReflection = kind === 'reflection'

  const del = async () => {
    setDeleting(true)
    try {
      await deleteEvolutionItem(kind, item.content)
      onDeleted(item.content)
      setOpen(false)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="group w-full flex items-center gap-2 rounded-lg border border-hairline bg-surface px-2.5 py-2 text-left hover:bg-elevated transition-colors duration-150 cursor-pointer"
        aria-label={`查看${isReflection ? '反思' : '技能'} ${item.date}`}
      >
        <Icon
          name={isReflection ? 'brain' : 'book'}
          size={13}
          className={isReflection ? 'text-[rgba(236,233,225,0.5)]' : 'text-primary/80'}
        />
        <span
          className={`flex-1 text-[12px] truncate ${
            isReflection ? 'text-[rgba(236,233,225,0.55)]' : 'text-[rgba(236,233,225,0.65)]'
          }`}
        >
          {isReflection ? '反思' : '技能'} · {item.date?.slice(5, 16)}
        </span>
        <Icon name="chevron-right" size={12} className="text-[rgba(236,233,225,0.3)]" />
      </button>

      <DetailModal
        title={`${isReflection ? '反思' : '技能'} · ${item.date?.slice(0, 16) ?? ''}`}
        open={open}
        onClose={() => setOpen(false)}
        footer={
          <button
            onClick={del}
            disabled={deleting}
            className="flex items-center gap-1 text-[12px] text-[rgba(236,233,225,0.6)] hover:text-error transition-colors disabled:opacity-50"
          >
            <Icon name="trash" size={12} />
            {deleting ? '删除中…' : '删除'}
          </button>
        }
      >
        {item.content}
      </DetailModal>
    </>
  )
}
