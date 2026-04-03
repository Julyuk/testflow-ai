import { Card, Button, Tag, Typography, Tooltip, Space } from 'antd'
import { RollbackOutlined, ReloadOutlined, EyeOutlined } from '@ant-design/icons'
import type { Checkpoint } from '@/types'

const { Text } = Typography

const STAGE_LABELS: Record<string, string> = {
  intake: 'Intake',
  refinement: 'Requirements Analysis',
  clarification_wait: 'Clarification',
  requirements_review: 'Requirements Review',
  test_case_generation: 'TC Generation',
  review_wait: 'TC Review',
  code_generation: 'Code Generation',
  validation: 'Validation',
  export: 'Export',
  completed: 'Completed',
}

const STAGE_COLORS: Record<string, string> = {
  intake: 'default',
  refinement: 'blue',
  clarification_wait: 'orange',
  requirements_review: 'volcano',
  test_case_generation: 'purple',
  review_wait: 'gold',
  code_generation: 'cyan',
  validation: 'geekblue',
  export: 'green',
  completed: 'green',
}

// Human review stages — restore lets the user re-edit and re-approve
const HUMAN_STAGES  = new Set(['clarification_wait', 'requirements_review', 'review_wait'])
// AI stages — additionally get a Rerun button to re-execute the agent
const AI_STAGES     = new Set(['refinement', 'test_case_generation', 'code_generation', 'validation'])
// Read-only result stages — restore so user can view/export without re-running
const RESULT_STAGES = new Set(['export', 'completed'])

// Label and tooltip for the primary restore button per stage type
function restoreLabel(stage: string): { label: string; tip: string } {
  if (stage === 'intake') return { label: 'Restart', tip: 'Restore to intake — re-enter requirements' }
  if (HUMAN_STAGES.has(stage)) return { label: 'Edit', tip: 'Restore this state to review and edit' }
  if (RESULT_STAGES.has(stage)) return { label: 'View', tip: 'Restore completed results without re-running' }
  return { label: 'Restore', tip: 'Restore pipeline state from this snapshot' }
}

interface Props {
  checkpoint: Checkpoint
  isActive: boolean
  onGoBack: (checkpoint: Checkpoint) => void
  onRerun: (checkpoint: Checkpoint) => void
  loading?: boolean
}

export default function StageCard({ checkpoint, isActive, onGoBack, onRerun, loading }: Props) {
  const label = STAGE_LABELS[checkpoint.stage] ?? checkpoint.stage
  const color = STAGE_COLORS[checkpoint.stage] ?? 'default'
  const date  = new Date(checkpoint.created_at).toLocaleTimeString()

  // Every non-active checkpoint can be restored (loads saved state, no agents re-run)
  const showRestore = !isActive
  // AI stages additionally offer Rerun (re-executes the agent from LangGraph checkpoint)
  const showRerun = !isActive && AI_STAGES.has(checkpoint.stage) && !!checkpoint.langgraph_checkpoint_id

  const { label: restoreBtnLabel, tip: restoreTip } = restoreLabel(checkpoint.stage)
  const isResultStage = RESULT_STAGES.has(checkpoint.stage)

  return (
    <Card
      size="small"
      style={{
        border: isActive ? '2px solid #1677ff' : undefined,
        marginBottom: 8,
      }}
      extra={
        showRestore ? (
          <Space size={4}>
            <Tooltip title={restoreTip}>
              <Button
                size="small"
                icon={isResultStage ? <EyeOutlined /> : <RollbackOutlined />}
                onClick={() => onGoBack(checkpoint)}
                loading={loading}
              >
                {restoreBtnLabel}
              </Button>
            </Tooltip>
            {showRerun && (
              <Tooltip title="Re-run AI agent from this checkpoint">
                <Button
                  size="small"
                  type="primary"
                  ghost
                  icon={<ReloadOutlined />}
                  onClick={() => onRerun(checkpoint)}
                  loading={loading}
                >
                  Rerun
                </Button>
              </Tooltip>
            )}
          </Space>
        ) : null
      }
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Tag color={color}>{label}</Tag>
        {isActive && <Tag color="blue">current</Tag>}
        <Text type="secondary" style={{ fontSize: 11, marginLeft: 'auto' }}>
          {date}
        </Text>
      </div>
    </Card>
  )
}
