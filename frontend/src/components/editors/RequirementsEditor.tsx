import { useState, useEffect } from 'react'
import { Card, Form, Input, Button, Typography, Space, Tooltip, Popconfirm } from 'antd'
import { SendOutlined, SaveOutlined, PlusOutlined, DeleteOutlined, CheckCircleOutlined } from '@ant-design/icons'
import type { PipelineState, Requirement } from '@/types'

const { TextArea } = Input
const { Title, Text } = Typography

const PLACEHOLDER = `Example:
- User should be able to log in with valid credentials
- Login should fail with incorrect password and show error message
- User should be able to add items to cart
- Cart total should update when item quantity changes`

interface Props {
  sessionId: string
  pipelineState: PipelineState | null
  onStart: (requirements: string) => Promise<void>
  onSaveRequirements?: (requirements: Requirement[]) => Promise<void>
  onApproveRequirements?: (requirements: Requirement[]) => Promise<void>
  loading?: boolean
}

export default function RequirementsEditor({
  sessionId: _sessionId,
  pipelineState,
  onStart,
  onSaveRequirements,
  onApproveRequirements,
  loading,
}: Props) {
  const [value, setValue] = useState(pipelineState?.raw_requirements ?? '')
  const [editedReqs, setEditedReqs] = useState<Requirement[]>([])
  const [saving, setSaving] = useState(false)
  const [approving, setApproving] = useState(false)

  // Sync editable requirements when pipeline state changes
  useEffect(() => {
    if (pipelineState?.requirements?.length) {
      setEditedReqs(pipelineState.requirements.map(r => ({ ...r, acceptance_criteria: [...r.acceptance_criteria] })))
    }
  }, [pipelineState?.requirements])

  const handleSubmit = async () => {
    if (!value.trim()) return
    await onStart(value.trim())
  }

  const handleSave = async () => {
    if (!onSaveRequirements) return
    setSaving(true)
    try {
      await onSaveRequirements(editedReqs)
    } finally {
      setSaving(false)
    }
  }

  const handleApprove = async () => {
    if (!onApproveRequirements) return
    setApproving(true)
    try {
      await onApproveRequirements(editedReqs)
    } finally {
      setApproving(false)
    }
  }

  const updateUserStory = (id: string, val: string) => {
    setEditedReqs(prev => prev.map(r => r.id === id ? { ...r, user_story: val } : r))
  }

  const updateCriterion = (reqId: string, idx: number, val: string) => {
    setEditedReqs(prev => prev.map(r =>
      r.id === reqId
        ? { ...r, acceptance_criteria: r.acceptance_criteria.map((c, i) => i === idx ? val : c) }
        : r
    ))
  }

  const addCriterion = (reqId: string) => {
    setEditedReqs(prev => prev.map(r =>
      r.id === reqId
        ? { ...r, acceptance_criteria: [...r.acceptance_criteria, ''] }
        : r
    ))
  }

  const removeCriterion = (reqId: string, idx: number) => {
    setEditedReqs(prev => prev.map(r =>
      r.id === reqId
        ? { ...r, acceptance_criteria: r.acceptance_criteria.filter((_, i) => i !== idx) }
        : r
    ))
  }

  const deleteRequirement = (id: string) => {
    setEditedReqs(prev => prev.filter(r => r.id !== id))
  }

  const addRequirement = () => {
    const newId = `REQ-${String(editedReqs.length + 1).padStart(3, '0')}`
    setEditedReqs(prev => [...prev, {
      id: newId,
      raw_text: '',
      user_story: '',
      acceptance_criteria: [],
      status: 'raw' as Requirement['status'],
    }])
  }

  // Show editable structured requirements when they exist
  if (pipelineState?.requirements?.length && editedReqs.length > 0) {
    return (
      <Card
        title={<Title level={5} style={{ margin: 0 }}>Structured Requirements</Title>}
        extra={
          <Space size={8}>
            {onSaveRequirements && (
              <Button
                size="small"
                icon={<SaveOutlined />}
                type="primary"
                ghost
                onClick={handleSave}
                loading={saving || loading}
              >
                Save Changes
              </Button>
            )}
          </Space>
        }
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          {editedReqs.map(req => (
            <Card
              key={req.id}
              size="small"
              type="inner"
              title={<Text code>{req.id}</Text>}
              extra={
                <Popconfirm
                  title="Delete this requirement?"
                  onConfirm={() => deleteRequirement(req.id)}
                  okText="Delete"
                  okButtonProps={{ danger: true }}
                >
                  <Tooltip title="Delete requirement">
                    <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                  </Tooltip>
                </Popconfirm>
              }
            >
              <div style={{ marginBottom: 10 }}>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                  User Story
                </Text>
                <TextArea
                  rows={2}
                  value={req.user_story ?? ''}
                  onChange={e => updateUserStory(req.id, e.target.value)}
                  style={{ fontSize: 13 }}
                />
              </div>
              <div>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                  Acceptance Criteria
                </Text>
                <Space direction="vertical" style={{ width: '100%' }} size={4}>
                  {req.acceptance_criteria.map((c, i) => (
                    <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      <Input
                        size="small"
                        value={c}
                        onChange={e => updateCriterion(req.id, i, e.target.value)}
                        style={{ fontSize: 12 }}
                      />
                      <Tooltip title="Remove">
                        <Button
                          size="small"
                          type="text"
                          danger
                          icon={<DeleteOutlined />}
                          onClick={() => removeCriterion(req.id, i)}
                        />
                      </Tooltip>
                    </div>
                  ))}
                  <Button
                    size="small"
                    type="dashed"
                    icon={<PlusOutlined />}
                    onClick={() => addCriterion(req.id)}
                  >
                    Add criterion
                  </Button>
                </Space>
              </div>
            </Card>
          ))}
        </Space>

        <Button
          type="dashed"
          icon={<PlusOutlined />}
          onClick={addRequirement}
          style={{ marginTop: 8 }}
          size="small"
        >
          Add Requirement
        </Button>

        {onApproveRequirements && (() => {
          const hasContent = editedReqs.length > 0 &&
            editedReqs.some(r => (r.user_story ?? '').trim().length > 0)
          return (
            <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid #f0f0f0' }}>
              {!hasContent && (
                <Text type="danger" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
                  At least one requirement must have a user story before approving.
                </Text>
              )}
              <Button
                type="primary"
                icon={<CheckCircleOutlined />}
                onClick={handleApprove}
                loading={approving || loading}
                disabled={!hasContent}
              >
                Approve Requirements & Generate Test Cases
              </Button>
            </div>
          )
        })()}
      </Card>
    )
  }

  return (
    <Card title={<Title level={5} style={{ margin: 0 }}>Requirements Intake</Title>}>
      <Form layout="vertical" onFinish={handleSubmit}>
        <Form.Item
          label="Describe what you want to test"
          extra="Plain English — one requirement per line"
        >
          <TextArea
            rows={8}
            value={value}
            onChange={e => setValue(e.target.value)}
            placeholder={PLACEHOLDER}
          />
        </Form.Item>
        <Button
          type="primary"
          htmlType="submit"
          icon={<SendOutlined />}
          loading={loading}
          disabled={!value.trim()}
        >
          Start Pipeline
        </Button>
      </Form>
    </Card>
  )
}
