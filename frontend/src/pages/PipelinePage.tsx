import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Row, Col, Card, Button, Typography, Space, Alert,
  Spin, Breadcrumb, Tag, Modal, Tooltip
} from 'antd'
import { ArrowLeftOutlined, HomeOutlined, ReloadOutlined, ExpandOutlined } from '@ant-design/icons'
import { useSessionStore } from '@/store/sessionStore'
import { useSession } from '@/hooks/useSession'
import PipelineView from '@/components/pipeline/PipelineView'
import StageCard from '@/components/pipeline/StageCard'
import RequirementsEditor from '@/components/editors/RequirementsEditor'
import ClarificationPanel from '@/components/editors/ClarificationPanel'
import TestCaseEditor from '@/components/editors/TestCaseEditor'
import CodeViewer from '@/components/editors/CodeViewer'
import AgentActivityLog from '@/components/common/AgentActivityLog'
import type { Checkpoint, TestCase, Requirement } from '@/types'

const { Title, Text } = Typography

const STATUS_COLOR: Record<string, string> = {
  created: 'default',
  running: 'processing',
  paused: 'warning',
  completed: 'success',
  error: 'error',
}

export default function PipelinePage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const navigate = useNavigate()

  const {
    sessions, activeSession, pipelineState, checkpoints, executions, activityLog, executionOutput,
    pipelineLoading, error,
    fetchSessions, setActiveSession,
    startPipeline, resumePipeline, returnToCheckpoint, restoreCheckpoint, editStage, executeTests, executeFile,
    clearError,
  } = useSessionStore()

  // Restore active session from URL if page was refreshed
  useEffect(() => {
    if (!activeSession && sessionId && sessions.length === 0) {
      fetchSessions().then(() => {
        const s = useSessionStore.getState().sessions.find(x => x.id === sessionId)
        if (s) setActiveSession(s)
      })
    } else if (!activeSession && sessionId) {
      const s = sessions.find(x => x.id === sessionId)
      if (s) setActiveSession(s)
    }
  }, [sessionId, activeSession, sessions, fetchSessions, setActiveSession])

  useSession(sessionId ?? null)

  const session = activeSession ?? sessions.find(s => s.id === sessionId) ?? null

  if (!session) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" />
      </div>
    )
  }

  const stage = pipelineState?.current_stage ?? session.current_stage ?? 'intake'
  const awaitingHuman = pipelineState?.awaiting_human ?? false

  // ── action handlers ────────────────────────────────────────────────────────

  const [starting, setStarting] = useState(false)
  const [historyExpanded, setHistoryExpanded] = useState(false)

  const handleStart = async (requirements: string) => {
    if (starting) return
    setStarting(true)
    try {
      await startPipeline(session.id, requirements)
    } finally {
      setStarting(false)
    }
  }

  const handleClarificationSubmit = async (answers: Record<string, string>) => {
    await resumePipeline(session.id, { answers })
  }

  const handleApproveTestCases = async (cases: TestCase[]) => {
    // Save edits to the review_wait snapshot, then resume with approve signal
    await editStage(session.id, 'review_wait', { test_cases: cases })
    await resumePipeline(session.id, { test_cases: cases, feedback: 'approve' })
  }

  const handleRegenerateTestCases = async (feedback: string) => {
    await resumePipeline(session.id, { feedback: `regenerate: ${feedback}` })
  }

  const handleExecute = async () => {
    await executeTests(session.id)
  }

  const handleExecuteFile = async (testNode: string) => {
    await executeFile(session.id, testNode)
  }

  const handleSaveRequirements = async (requirements: Requirement[]) => {
    // Save to the snapshot that owns the current stage, not always 'refinement'
    const snapshotStage = stage === 'requirements_review' ? 'requirements_review' : 'refinement'
    await editStage(session.id, snapshotStage, { requirements })
  }

  const handleApproveRequirements = async (requirements: Requirement[]) => {
    await resumePipeline(session.id, { requirements, action: 'approve' })
  }

  const handleGoBack = async (checkpoint: Checkpoint) => {
    // Restore state from DB snapshot WITHOUT re-running any agents
    await restoreCheckpoint(session.id, checkpoint.id)
  }

  const handleRerunFromCheckpoint = async (checkpoint: Checkpoint) => {
    if (checkpoint.langgraph_checkpoint_id) {
      await returnToCheckpoint(session.id, checkpoint.langgraph_checkpoint_id)
    }
  }

  // ── active panel based on stage ────────────────────────────────────────────

  const renderActivePanel = () => {
    if (!pipelineState && stage === 'intake') {
      return (
        <RequirementsEditor
          sessionId={session.id}
          pipelineState={pipelineState}
          onStart={handleStart}
          loading={pipelineLoading || starting}
        />
      )
    }

    if (!pipelineState) {
      return (
        <Card>
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin />
            <Text type="secondary" style={{ display: 'block', marginTop: 12 }}>
              Loading pipeline state...
            </Text>
          </div>
        </Card>
      )
    }

    // Show requirements intake / structured requirements (editable)
    if (stage === 'intake' || stage === 'refinement') {
      return (
        <RequirementsEditor
          sessionId={session.id}
          pipelineState={pipelineState}
          onStart={handleStart}
          onSaveRequirements={pipelineState?.requirements?.length ? handleSaveRequirements : undefined}
          loading={pipelineLoading || starting}
        />
      )
    }

    // Clarification — show whenever at this stage with questions available
    if (stage === 'clarification_wait' && pipelineState.clarification_questions?.length > 0) {
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {pipelineState.requirements?.length > 0 && (
            <RequirementsEditor
              sessionId={session.id}
              pipelineState={pipelineState}
              onStart={handleStart}
              onSaveRequirements={handleSaveRequirements}
              loading={pipelineLoading || starting}
            />
          )}
          <ClarificationPanel
            questions={pipelineState.clarification_questions}
            onSubmit={handleClarificationSubmit}
            loading={pipelineLoading || starting}
          />
        </div>
      )
    }

    // Requirements review — show whenever we're at this stage
    if (stage === 'requirements_review') {
      // Requirements are ready: show the editable review panel with approve button
      if (pipelineState.requirements?.length > 0) {
        return (
          <RequirementsEditor
            sessionId={session.id}
            pipelineState={pipelineState}
            onStart={handleStart}
            onSaveRequirements={handleSaveRequirements}
            onApproveRequirements={handleApproveRequirements}
            loading={pipelineLoading || starting}
          />
        )
      }
      // Still waiting for the AI to finish structuring
      return (
        <Card>
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin />
            <Text type="secondary" style={{ display: 'block', marginTop: 12 }}>
              Analyzing requirements...
            </Text>
          </div>
        </Card>
      )
    }

    // Generating test cases — show spinner while AI works
    if (stage === 'test_case_generation' && !awaitingHuman) {
      return (
        <Card>
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin />
            <Text type="secondary" style={{ display: 'block', marginTop: 12 }}>
              Generating test cases...
            </Text>
          </div>
        </Card>
      )
    }

    // Review test cases — show whenever test cases are available
    if (
      (stage === 'review_wait' || stage === 'test_case_generation') &&
      pipelineState.test_cases?.length > 0
    ) {
      return (
        <TestCaseEditor
          testCases={pipelineState.test_cases}
          onApprove={handleApproveTestCases}
          onRegenerate={handleRegenerateTestCases}
          loading={pipelineLoading || starting}
        />
      )
    }

    // Code generated / validation
    if (
      ['code_generation', 'validation', 'export', 'completed'].includes(stage) &&
      Object.keys(pipelineState.generated_tests ?? {}).length > 0
    ) {
      return (
        <CodeViewer
          sessionId={session.id}
          generatedTests={pipelineState.generated_tests}
          validationResults={pipelineState.validation_results ?? []}
          executions={executions}
          testCases={pipelineState.test_cases ?? []}
          executionOutput={executionOutput}
          onExecute={handleExecute}
          onExecuteFile={handleExecuteFile}
          loading={pipelineLoading || starting}
        />
      )
    }

    // Detect restored state where the stage implies code generation but no tests exist yet
    // and the pipeline is not actively running — avoid showing an infinite spinner
    if (
      ['code_generation', 'validation'].includes(stage) &&
      Object.keys(pipelineState.generated_tests ?? {}).length === 0 &&
      !pipelineLoading
    ) {
      return (
        <Card>
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
              State restored to <Text code>{stage}</Text> stage.
            </Text>
            <Text type="secondary">
              Use <Text strong>Rerun</Text> in Stage History to regenerate the test code.
            </Text>
          </div>
        </Card>
      )
    }

    // Fallback — pipeline actively running
    return (
      <Card>
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin />
          <Text type="secondary" style={{ display: 'block', marginTop: 12 }}>
            Pipeline is running...
          </Text>
        </div>
      </Card>
    )
  }

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      <Breadcrumb
        style={{ marginBottom: 16 }}
        items={[
          {
            href: '/',
            title: <Space size={4}><HomeOutlined /><span>Sessions</span></Space>,
          },
          { title: session.name },
        ]}
      />

      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 20, gap: 12 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>
          Back
        </Button>
        <Title level={4} style={{ margin: 0 }}>{session.name}</Title>
        <Tag color={STATUS_COLOR[session.status] ?? 'default'}>{session.status}</Tag>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {session.target_url}
        </Text>
        {session.status === 'error' && (
          <Button
            icon={<ReloadOutlined />}
            danger
            size="small"
            style={{ marginLeft: 'auto' }}
            onClick={() => {
              const reqs = pipelineState?.raw_requirements
              if (reqs) handleStart(reqs)
            }}
            loading={starting || pipelineLoading}
          >
            Restart Pipeline
          </Button>
        )}
      </div>

      {error && (
        <Alert
          type="error"
          message={error}
          closable
          onClose={clearError}
          style={{ marginBottom: 16 }}
        />
      )}

      {/* Pipeline progress bar */}
      <Card style={{ marginBottom: 16 }}>
        <PipelineView currentStage={stage} awaitingHuman={awaitingHuman} />
      </Card>

      <Row gutter={16}>
        {/* Main content area */}
        <Col xs={24} lg={17}>
          {renderActivePanel()}
        </Col>

        {/* Checkpoint sidebar */}
        <Col xs={24} lg={7}>
          <AgentActivityLog entries={activityLog} loading={pipelineLoading || starting} />
          <Card
            style={{ marginTop: 16 }}
            title={
              <Text strong style={{ fontSize: 13 }}>
                Stage History
              </Text>
            }
            size="small"
            extra={
              <Space size={6}>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  Restore or rerun from a stage
                </Text>
                {checkpoints.length > 0 && (
                  <Tooltip title="Expand history">
                    <Button
                      type="text"
                      size="small"
                      icon={<ExpandOutlined />}
                      onClick={() => setHistoryExpanded(true)}
                      style={{ color: '#8b949e' }}
                    />
                  </Tooltip>
                )}
              </Space>
            }
          >
            {checkpoints.length === 0 ? (
              <Text type="secondary" style={{ fontSize: 12 }}>
                No checkpoints yet. Start the pipeline to see history here.
              </Text>
            ) : (
              [...checkpoints].reverse().map(cp => (
                <StageCard
                  key={cp.id}
                  checkpoint={cp}
                  isActive={cp.stage === stage}
                  onGoBack={handleGoBack}
                  onRerun={handleRerunFromCheckpoint}
                  loading={pipelineLoading || starting}
                />
              ))
            )}
          </Card>

          <Modal
            open={historyExpanded}
            onCancel={() => setHistoryExpanded(false)}
            footer={null}
            title={
              <Space size={6}>
                <Text strong>Stage History</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {checkpoints.length} checkpoint{checkpoints.length !== 1 ? 's' : ''}
                </Text>
              </Space>
            }
            width="60vw"
            destroyOnHidden
            styles={{ body: { maxHeight: '70vh', overflowY: 'auto', paddingTop: 8 } }}
          >
            {[...checkpoints].reverse().map(cp => (
              <StageCard
                key={cp.id}
                checkpoint={cp}
                isActive={cp.stage === stage}
                onGoBack={(c) => { handleGoBack(c); setHistoryExpanded(false) }}
                onRerun={(c) => { handleRerunFromCheckpoint(c); setHistoryExpanded(false) }}
                loading={pipelineLoading || starting}
              />
            ))}
          </Modal>
        </Col>
      </Row>
    </div>
  )
}
