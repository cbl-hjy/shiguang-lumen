/* 知识库治理权 API（最小落地清单⑤，2026-08-20）：可见/可删(回收站)/可改名 */
export interface KbDocument {
  id: string
  title: string
  size: number
  mtime: number
  vectors: number
}

export async function listKbDocs(): Promise<KbDocument[]> {
  const res = await fetch('/api/kb/documents')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const d = await res.json()
  return d.documents ?? []
}

export async function deleteKbDoc(docId: string): Promise<{ ok: boolean; msg?: string }> {
  const res = await fetch(`/api/kb/documents/${encodeURIComponent(docId)}`, { method: 'DELETE' })
  return res.json()
}

export async function renameKbDoc(docId: string, title: string): Promise<{ ok: boolean; msg?: string }> {
  const res = await fetch(`/api/kb/documents/${encodeURIComponent(docId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
  return res.json()
}
