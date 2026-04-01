import { create } from 'zustand'
import axios from 'axios'
import type { Session, PipelineState, Checkpoint, ExecutionResult, ActivityLogEntry } from '@/types'
import { sessionsApi, pipelineApi } from '@/api/client'

function extractErrorMessage(e: unknown): string {
  if (axios.isAxiosError(e)) {
    return e.response?.data?.detail ?? e.message
  }
  return String(e)
}

interface SessionStore {
  // Sessions list
  sessions: Session[]
  sessionsLoading: boolean

  // Active session
  activeSession: Session | null
  pipelineState: PipelineState | null
  checkpoints: Checkpoint[]
  executions: ExecutionResult[]
  activityLog: ActivityLogEntry[]
  executionOutput: string[]   // live pytest stdout lines during an active test run
  pipelineLoading: boolean
  error: string | null

  // Actions
  fetchSessions: () => Promise<void>
  createSession: (name: string, description: string, targetUrl: string) => Promise<Session>
  deleteSession: (id: string) => Promise<void>
  setActiveSession: (session: Session) => void

  fetchPipelineState: (sessionId: string) => Promise<void>
  fetchCheckpoints: (sessionId: string) => Promise<void>
  fetchExecutions: (sessionId: string) => Promise<void>

  startPipeline: (sessionId: string, requirements: string) => Promise<PipelineState>
  resumePipeline: (sessionId: string, answer: Record<string, unknown>) => Promise<PipelineState>
  returnToCheckpoint: (sessionId: string, checkpointId: string) => Promise<PipelineState>
  restoreCheckpoint: (sessionId: string, snapshotId: string) => Promise<PipelineState>
  editStage: (sessionId: string, stage: string, data: Record<string, unknown>) => Promise<void>
  executeTests: (sessionId: string) => Promise<ExecutionResult>
  executeFile: (sessionId: string, testNode: string) => Promise<void>

  // Called from WebSocket to push live updates
  applyStateUpdate: (state: PipelineState) => void
  applyExecutionDone: (result: ExecutionResult) => void
  appendExecutionOutput: (line: string) => void
  clearExecutionOutput: () => void
  appendActivityLog: (entry: ActivityLogEntry) => void
  clearActivityLog: () => void

  clearError: () => void
}

export const useSessionStore = create<SessionStore>((set, get) => ({
  sessions: [],
  sessionsLoading: false,
  activeSession: null,
  pipelineState: null,
  checkpoints: [],
  executions: [],
  activityLog: [],
  executionOutput: [],
  pipelineLoading: false,
  error: null,

  fetchSessions: async () => {
    set({ sessionsLoading: true })
    try {
      const sessions = await sessionsApi.list()
      set({ sessions, sessionsLoading: false, error: null })
    } catch (e: unknown) {
      set({ sessionsLoading: false, error: extractErrorMessage(e) })
    }
  },

  createSession: async (name, description, targetUrl) => {
    const session = await sessionsApi.create({
      name,
      description,
      target_url: targetUrl,
    })
    set(s => ({ sessions: [session, ...s.sessions] }))
    return session
  },

  deleteSession: async (id) => {
    await sessionsApi.delete(id)
    set(s => ({
      sessions: s.sessions.filter(x => x.id !== id),
      activeSession: s.activeSession?.id === id ? null : s.activeSession,
    }))
  },

  setActiveSession: (session) => {
    set({ activeSession: session, pipelineState: null, checkpoints: [], executions: [], error: null })
  },

  fetchPipelineState: async (sessionId) => {
    try {
      const { state } = await pipelineApi.getState(sessionId)
      set({ pipelineState: state })
    } catch (e: unknown) {
      set({ error: extractErrorMessage(e) })
    }
  },

  fetchCheckpoints: async (sessionId) => {
    try {
      const { checkpoints } = await pipelineApi.listCheckpoints(sessionId)
      set({ checkpoints })
    } catch (e: unknown) {
      set({ error: extractErrorMessage(e) })
    }
  },

  fetchExecutions: async (sessionId) => {
    try {
      const { results } = await pipelineApi.listExecutions(sessionId)
      set({ executions: results })
    } catch (e: unknown) {
      set({ error: extractErrorMessage(e) })
    }
  },

  startPipeline: async (sessionId, requirements) => {
    set({ pipelineLoading: true, error: null })
    try {
      const { state } = await pipelineApi.start(sessionId, requirements)
      set({ pipelineState: state, pipelineLoading: false })
      get().fetchCheckpoints(sessionId)
      return state
    } catch (e: unknown) {
      set({ pipelineLoading: false, error: extractErrorMessage(e) })
      throw e
    }
  },

  resumePipeline: async (sessionId, answer) => {
    set({ pipelineLoading: true, error: null })
    try {
      const { state } = await pipelineApi.resume(sessionId, answer)
      set({ pipelineState: state, pipelineLoading: false })
      get().fetchCheckpoints(sessionId)
      return state
    } catch (e: unknown) {
      set({ pipelineLoading: false, error: extractErrorMessage(e) })
      throw e
    }
  },

  returnToCheckpoint: async (sessionId, checkpointId) => {
    set({ pipelineLoading: true, error: null })
    try {
      const { state } = await pipelineApi.returnToCheckpoint(sessionId, checkpointId)
      set({ pipelineState: state, pipelineLoading: false })
      get().fetchCheckpoints(sessionId)
      return state
    } catch (e: unknown) {
      set({ pipelineLoading: false, error: extractErrorMessage(e) })
      throw e
    }
  },

  restoreCheckpoint: async (sessionId, snapshotId) => {
    set({ pipelineLoading: true, error: null })
    try {
      const { state } = await pipelineApi.restoreCheckpoint(sessionId, snapshotId)
      set({ pipelineState: state, pipelineLoading: false })
      get().fetchCheckpoints(sessionId)
      return state
    } catch (e: unknown) {
      set({ pipelineLoading: false, error: extractErrorMessage(e) })
      throw e
    }
  },

  editStage: async (sessionId, stage, data) => {
    await pipelineApi.editStage(sessionId, stage, data)
  },

  executeTests: async (sessionId) => {
    set({ pipelineLoading: true, error: null, executionOutput: [] })
    try {
      const result = await pipelineApi.execute(sessionId)
      // Do NOT push to executions here — applyExecutionDone (WS execution_done) is the
      // single source of truth so we never get a duplicate entry.
      // After the HTTP response, refresh from DB to ensure IDs + timestamps are present.
      set({ pipelineLoading: false, executionOutput: [] })
      await get().fetchExecutions(sessionId)
      return result
    } catch (e: unknown) {
      set({ pipelineLoading: false, error: extractErrorMessage(e), executionOutput: [] })
      throw e
    }
  },

  executeFile: async (sessionId, testNode) => {
    set({ pipelineLoading: true, error: null, executionOutput: [] })
    try {
      await pipelineApi.executeFile(sessionId, testNode)
      set({ pipelineLoading: false, executionOutput: [] })
      await get().fetchExecutions(sessionId)
    } catch (e: unknown) {
      set({ pipelineLoading: false, error: extractErrorMessage(e), executionOutput: [] })
      throw e
    }
  },

  applyStateUpdate: (state) => {
    set({ pipelineState: state })
  },

  applyExecutionDone: (_result) => {
    // Clear live output and loading immediately on completion.
    // executeTests (HTTP handler) calls fetchExecutions() to get the canonical DB list,
    // so we intentionally do NOT prepend here to avoid duplicates.
    set({ pipelineLoading: false, executionOutput: [] })
  },

  appendExecutionOutput: (line) => {
    set(s => ({ executionOutput: [...s.executionOutput.slice(-500), line] }))
  },

  clearExecutionOutput: () => set({ executionOutput: [] }),

  appendActivityLog: (entry) => {
    set(s => ({ activityLog: [...s.activityLog.slice(-199), entry] }))
  },

  clearActivityLog: () => set({ activityLog: [] }),

  clearError: () => set({ error: null }),
}))
