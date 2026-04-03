import { Steps, Tag, Typography } from 'antd'
import type { StageKey } from '@/types'

const { Text } = Typography

const STAGES: { key: StageKey; label: string }[] = [
  { key: 'intake',              label: 'Intake' },
  { key: 'refinement',          label: 'Analysis' },
  { key: 'clarification_wait',  label: 'Clarification' },
  { key: 'requirements_review', label: 'Req. Review' },
  { key: 'test_case_generation',label: 'TC Generation' },
  { key: 'review_wait',         label: 'TC Review' },
  { key: 'code_generation',     label: 'Code Gen' },
  { key: 'validation',          label: 'Validation' },
  { key: 'export',              label: 'Export' },
]

const STAGE_ORDER = STAGES.map(s => s.key)

function stageIndex(stage: StageKey | string): number {
  if (stage === 'completed') return STAGES.length  // all steps finished
  const idx = STAGE_ORDER.indexOf(stage as StageKey)
  return idx === -1 ? 0 : idx
}

interface Props {
  currentStage: StageKey | string
  awaitingHuman?: boolean
}

export default function PipelineView({ currentStage, awaitingHuman }: Props) {
  const current = stageIndex(currentStage)
  const isCompleted = currentStage === 'completed'

  const items = STAGES.map((s, i) => {
    const isActive = s.key === currentStage
    const isPast = i < current
    const status: 'finish' | 'process' | 'wait' = (isPast || isCompleted)
      ? 'finish'
      : isActive ? 'process' : 'wait'

    return {
      title: <span style={{ whiteSpace: 'nowrap' }}>{s.label}</span>,
      status,
    }
  })

  const activeLabel = STAGES.find(s => s.key === currentStage)?.label ?? currentStage

  return (
    <div>
      <Steps
        current={isCompleted ? STAGES.length : current}
        items={items}
        size="small"
        style={{ padding: '8px 0' }}
      />
      {awaitingHuman && !isCompleted && (
        <div style={{
          marginTop: 8,
          padding: '6px 12px',
          background: '#fff7e6',
          border: '1px solid #ffd591',
          borderRadius: 6,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}>
          <Tag color="orange" style={{ margin: 0 }}>waiting</Tag>
          <Text style={{ fontSize: 12, color: '#d46b08' }}>
            Waiting for your input at <strong>{activeLabel}</strong>
          </Text>
        </div>
      )}
    </div>
  )
}
