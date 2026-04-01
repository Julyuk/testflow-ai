import axios from 'axios'
import type {
  Session,
  PipelineState,
  Checkpoint,
  ExecutionResult,
  AzureDevOpsConfig,
} from '@/types'

const http = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
})

// ── Sessions ──────────────────────────────────────────────────────────────────

export const sessionsApi = {
  list: () => http.get<Session[]>('/sessions/').then(r => r.data),

  create: (payload: { name: string; description?: string; target_url?: string }) =>
    http.post<Session>('/sessions/', payload).then(r => r.data),

  get: (id: string) => http.get<Session>(`/sessions/${id}`).then(r => r.data),

  delete: (id: string) => http.delete(`/sessions/${id}`),
}

// ── Pipeline ──────────────────────────────────────────────────────────────────

export const pipelineApi = {
  start: (session_id: string, raw_requirements: string) =>
    http
      .post<{ status: string; state: PipelineState }>('/pipeline/start', {
        session_id,
        raw_requirements,
      })
      .then(r => r.data),

  resume: (session_id: string, answer: Record<string, unknown>) =>
    http
      .post<{ status: string; state: PipelineState }>('/pipeline/resume', {
        session_id,
        answer,
      })
      .then(r => r.data),

  returnToCheckpoint: (session_id: string, checkpoint_id: string) =>
    http
      .post<{ status: string; state: PipelineState }>('/pipeline/return-to-checkpoint', {
        session_id,
        checkpoint_id,
      })
      .then(r => r.data),

  restoreCheckpoint: (session_id: string, snapshot_id: string) =>
    http
      .post<{ status: string; state: PipelineState; stage: string }>(
        `/pipeline/${session_id}/restore-checkpoint`,
        { snapshot_id }
      )
      .then(r => r.data),

  editStage: (session_id: string, stage: string, data: Record<string, unknown>) =>
    http
      .patch<{ status: string }>(`/pipeline/${session_id}/stage/${stage}`, { data })
      .then(r => r.data),

  getState: (session_id: string) =>
    http
      .get<{ state: PipelineState | null; stage: string }>(`/pipeline/${session_id}/state`)
      .then(r => r.data),

  listCheckpoints: (session_id: string) =>
    http
      .get<{ checkpoints: Checkpoint[] }>(`/pipeline/${session_id}/checkpoints`)
      .then(r => r.data),

  execute: (session_id: string) =>
    http
      .post<ExecutionResult>(`/pipeline/${session_id}/execute`)
      .then(r => r.data),

  listExecutions: (session_id: string) =>
    http
      .get<{ results: ExecutionResult[] }>(`/pipeline/${session_id}/executions`)
      .then(r => r.data),

  explainFailure: (
    session_id: string,
    test_name: string,
    traceback: string,
    test_case?: Record<string, unknown> | null,
  ) =>
    http
      .post<{ explanation: { failed_step: string; root_cause: string; fix: string; code_example: string } }>(
        `/pipeline/${session_id}/explain-failure`,
        { test_name, traceback, test_case: test_case ?? null }
      )
      .then(r => r.data),

  regenerateTest: (
    session_id: string,
    filename: string,
    traceback: string,
    test_case?: Record<string, unknown> | null,
    feedback?: string,
  ) =>
    http
      .post<{ filename: string; code: string }>(`/pipeline/${session_id}/regenerate-test`, {
        filename,
        traceback,
        test_case: test_case ?? null,
        feedback: feedback ?? null,
      })
      .then(r => r.data),

  executeFile: (session_id: string, test_node: string) =>
    http
      .post<ExecutionResult>(`/pipeline/${session_id}/execute-file`, { test_node })
      .then(r => r.data),

  downloadZip: (session_id: string) =>
    window.open(`/api/pipeline/${session_id}/download`, '_blank'),

  downloadGithubActions: (session_id: string) =>
    window.open(`/api/pipeline/${session_id}/ci/github-actions`, '_blank'),

  downloadAzurePipelines: (session_id: string) =>
    window.open(`/api/pipeline/${session_id}/ci/azure-pipelines`, '_blank'),
}

// ── Integrations ──────────────────────────────────────────────────────────────

export const integrationsApi = {
  getAzureConfig: () =>
    http.get<AzureDevOpsConfig>('/integrations/azure-devops').then(r => r.data),

  saveAzureConfig: (org: string, project: string, pat: string) =>
    http
      .post('/integrations/azure-devops', { organization: org, project, pat })
      .then(r => r.data),

  deleteAzureConfig: () =>
    http.delete('/integrations/azure-devops').then(r => r.data),

  syncToAzure: (session_id: string, test_plan_name: string) =>
    http
      .post('/integrations/azure-devops/sync', { session_id, test_plan_name })
      .then(r => r.data),
}
