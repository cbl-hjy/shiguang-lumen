import { create } from 'zustand'

/* 全局 UI 状态：Cmd+K 面板 / 思考过程显隐（用户自选，替代写死开关） */
interface UiState {
  commandOpen: boolean
  showThinking: boolean
  setCommandOpen: (v: boolean) => void
  toggleThinking: () => void
}

export const useUiStore = create<UiState>((set) => ({
  commandOpen: false,
  showThinking: true,
  setCommandOpen: (v) => set({ commandOpen: v }),
  toggleThinking: () => set((s) => ({ showThinking: !s.showThinking })),
}))
