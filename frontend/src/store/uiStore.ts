import { create } from 'zustand'

/* 全局 UI 状态：Cmd+K 面板 / 思考过程显隐（用户自选，替代写死开关）
   panelTab：左栏 PathPanel 的 tab（受控——命令面板/顶栏都能切，2026-08-20 修命令面板桌面端不生效根因） */
export type PanelTab = 'path' | 'memory'

interface UiState {
  commandOpen: boolean
  showThinking: boolean
  panelTab: PanelTab
  setCommandOpen: (v: boolean) => void
  toggleThinking: () => void
  setPanelTab: (t: PanelTab) => void
}

export const useUiStore = create<UiState>((set) => ({
  commandOpen: false,
  showThinking: true,
  panelTab: 'path',
  setCommandOpen: (v) => set({ commandOpen: v }),
  toggleThinking: () => set((s) => ({ showThinking: !s.showThinking })),
  setPanelTab: (t) => set({ panelTab: t }),
}))
