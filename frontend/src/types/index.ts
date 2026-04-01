// ── Domain types mirroring backend schemas ────────────────────────────────────

export type SessionStatus = 'created' | 'running' | 'paused' | 'completed' | 'error'

export interface Session {
  id: string
  name: string
  description: string
  target_url: string
  status: SessionStatus
  current_stage: string
  created_at: string
}

export type StageKey =
  | 'intake'
  | 'refinement'
  | 'clarification_wait'
  | 'requirements_review'
  | 'test_case_generation'
  | 'review_wait'
  | 'code_generation'
  | 'validation'
  | 'export'
  | 'completed'
  | 'error'

export interface TestStep {
  action: string
  expected_result: string
}

export interface TestCase {
  id: string
  title: string
  requirement_id: string
  type: 'happy_path' | 'negative' | 'edge_case' | 'security'
  priority: 'critical' | 'high' | 'medium' | 'low'
  preconditions: string[]
  steps: TestStep[]
  tags: string[]
  approved: boolean
}

export interface Requirement {
  id: string
  raw_text: string
  user_story?: string
  acceptance_criteria: string[]
  status: 'raw' | 'structured' | 'approved'
}

export interface ValidationResult {
  filename: string
  passed: boolean
  errors: string[]
  warnings: string[]
}

export interface PipelineState {
  session_id: string
  current_stage: StageKey
  raw_requirements: string
  requirements: Requirement[]
  clarification_questions: string[]
  clarification_answers: Record<string, string>
  test_cases: TestCase[]
  generated_tests: Record<string, string>
  validation_results: ValidationResult[]
  awaiting_human: boolean
  error?: string
  retry_count: number
}

export interface Checkpoint {
  id: string
  stage: StageKey
  langgraph_checkpoint_id: string | null
  created_at: string
}

export interface ExecutionResult {
  id: string
  status: 'running' | 'passed' | 'failed' | 'error'
  test_count: number
  pass_count: number
  fail_count: number
  stdout: string
  stderr: string
  created_at: string
}

export interface ActivityLogEntry {
  agent: string
  message: string
  level: 'info' | 'success' | 'warning' | 'error'
  timestamp: number
}

export interface AzureDevOpsConfig {
  configured: boolean
  organization?: string
  project?: string
  pat?: string
}

// ── WebSocket event shapes ────────────────────────────────────────────────────

export type WsEvent =
  | { type: 'stage_update'; stage: StageKey; state: PipelineState }
  | { type: 'execution_done'; result: ExecutionResult }
  | { type: 'execution_output'; line: string }
  | { type: 'activity_log'; agent: string; message: string; level: string }
  | { type: 'heartbeat' }
