import { useState, useEffect } from 'react'
import {
  Card, Table, Tag, Button, Space, Typography, Checkbox,
  Collapse, Tooltip, Modal, Input, Form, Select, Radio
} from 'antd'
import {
  ReloadOutlined, PlayCircleOutlined, EditOutlined,
  PlusOutlined, DeleteOutlined, SaveOutlined,
} from '@ant-design/icons'
import type { TestCase, TestStep } from '@/types'

const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

const PRIORITY_COLOR: Record<string, string> = {
  critical: 'red',
  high: 'orange',
  medium: 'blue',
  low: 'default',
}

const TYPE_COLOR: Record<string, string> = {
  happy_path: 'green',
  negative: 'red',
  edge_case: 'purple',
  security: 'magenta',
}

interface Props {
  testCases: TestCase[]
  onApprove: (cases: TestCase[]) => Promise<void>
  onRegenerate: (feedback: string) => Promise<void>
  loading?: boolean
}

// Deep-copy a test case for safe editing
function cloneCase(tc: TestCase): TestCase {
  return {
    ...tc,
    preconditions: [...tc.preconditions],
    steps: tc.steps.map(s => ({ ...s })),
    tags: [...tc.tags],
  }
}

export default function TestCaseEditor({ testCases, onApprove, onRegenerate, loading }: Props) {
  const [cases, setCases] = useState<TestCase[]>(() => testCases.map(cloneCase))

  useEffect(() => {
    setCases(testCases.map(cloneCase))
  }, [testCases])

  const [regenerateModalOpen, setRegenerateModalOpen] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [editingCase, setEditingCase] = useState<TestCase | null>(null)
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [priorityFilter, setPriorityFilter] = useState<string>('all')

  const toggleApprove = (id: string) => {
    setCases(prev => prev.map(tc => tc.id === id ? { ...tc, approved: !tc.approved } : tc))
  }

  const approveAll = () => setCases(prev => prev.map(tc => ({ ...tc, approved: true })))
  const deselectAll = () => setCases(prev => prev.map(tc => ({ ...tc, approved: false })))

  const openEdit = (tc: TestCase) => {
    setEditingCase(cloneCase(tc))
  }

  const saveEdit = () => {
    if (!editingCase) return
    setCases(prev => prev.map(tc => tc.id === editingCase.id ? { ...editingCase } : tc))
    setEditingCase(null)
  }

  const handleRegenerate = async () => {
    setRegenerateModalOpen(false)
    await onRegenerate(feedback || 'regenerate')
    setFeedback('')
  }

  // Editing helpers for the edit modal
  const setEditField = <K extends keyof TestCase>(key: K, val: TestCase[K]) => {
    setEditingCase(prev => prev ? { ...prev, [key]: val } : prev)
  }

  const updatePrecondition = (idx: number, val: string) => {
    setEditingCase(prev => {
      if (!prev) return prev
      const updated = [...prev.preconditions]
      updated[idx] = val
      return { ...prev, preconditions: updated }
    })
  }
  const addPrecondition = () =>
    setEditingCase(prev => prev ? { ...prev, preconditions: [...prev.preconditions, ''] } : prev)
  const removePrecondition = (idx: number) =>
    setEditingCase(prev => prev ? { ...prev, preconditions: prev.preconditions.filter((_, i) => i !== idx) } : prev)

  const updateStep = (idx: number, field: keyof TestStep, val: string) => {
    setEditingCase(prev => {
      if (!prev) return prev
      const steps = prev.steps.map((s, i) => i === idx ? { ...s, [field]: val } : s)
      return { ...prev, steps }
    })
  }
  const addStep = () =>
    setEditingCase(prev => prev ? { ...prev, steps: [...prev.steps, { action: '', expected_result: '' }] } : prev)
  const removeStep = (idx: number) =>
    setEditingCase(prev => prev ? { ...prev, steps: prev.steps.filter((_, i) => i !== idx) } : prev)

  const visibleCases = cases.filter(tc =>
    (typeFilter === 'all' || tc.type === typeFilter) &&
    (priorityFilter === 'all' || tc.priority === priorityFilter)
  )
  const approvedCount = cases.filter(tc => tc.approved).length
  const incompleteApproved = cases.filter(tc => tc.approved && (!tc.title.trim() || tc.steps.length === 0))

  const columns = [
    {
      title: '',
      dataIndex: 'approved',
      width: 40,
      render: (_: boolean, record: TestCase) => (
        <Checkbox checked={record.approved} onChange={() => toggleApprove(record.id)} />
      ),
    },
    {
      title: 'ID',
      dataIndex: 'id',
      width: 80,
      render: (id: string) => <Text code style={{ fontSize: 11 }}>{id}</Text>,
    },
    {
      title: 'Title',
      dataIndex: 'title',
      render: (title: string, record: TestCase) => (
        <Collapse
          ghost
          size="small"
          items={[
            {
              key: '1',
              label: (
                <Space size={4}>
                  <Text style={{ fontSize: 13 }}>{title}</Text>
                </Space>
              ),
              children: (
                <Space direction="vertical" size="small" style={{ width: '100%' }}>
                  {record.preconditions.length > 0 && (
                    <div>
                      <Text type="secondary" style={{ fontSize: 12 }}>Preconditions:</Text>
                      <ul style={{ paddingLeft: 16, margin: '4px 0' }}>
                        {record.preconditions.map((p, i) => (
                          <li key={i}><Text style={{ fontSize: 12 }}>{p}</Text></li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <div>
                    <Text type="secondary" style={{ fontSize: 12 }}>Steps:</Text>
                    <ol style={{ paddingLeft: 16, margin: '4px 0' }}>
                      {record.steps.map((s, i) => (
                        <li key={i} style={{ marginBottom: 4 }}>
                          <Text style={{ fontSize: 12 }}>{s.action}</Text>
                          <br />
                          <Text type="secondary" style={{ fontSize: 11 }}>→ {s.expected_result}</Text>
                        </li>
                      ))}
                    </ol>
                  </div>
                  <Button
                    size="small"
                    icon={<EditOutlined />}
                    onClick={e => { e.stopPropagation(); openEdit(record) }}
                  >
                    Edit
                  </Button>
                </Space>
              ),
            },
          ]}
        />
      ),
    },
    {
      title: 'Type',
      dataIndex: 'type',
      width: 110,
      render: (t: string) => <Tag color={TYPE_COLOR[t] ?? 'default'}>{t.replace(/_/g, ' ')}</Tag>,
    },
    {
      title: 'Priority',
      dataIndex: 'priority',
      width: 90,
      render: (p: string) => <Tag color={PRIORITY_COLOR[p] ?? 'default'}>{p}</Tag>,
    },
  ]

  return (
    <>
      <Card
        title={
          <Space>
            <Title level={5} style={{ margin: 0 }}>Test Cases</Title>
            <Text type="secondary" style={{ fontSize: 13 }}>
              {approvedCount} / {cases.length} selected
            </Text>
          </Space>
        }
        extra={
          <Space>
            <Button size="small" onClick={approveAll}>Select All</Button>
            <Button size="small" onClick={deselectAll} disabled={approvedCount === 0}>Deselect All</Button>
            <Tooltip title="Ask AI to regenerate with your feedback">
              <Button
                size="small"
                icon={<ReloadOutlined />}
                onClick={() => setRegenerateModalOpen(true)}
                loading={loading}
              >
                Regenerate
              </Button>
            </Tooltip>
          </Space>
        }
      >
        {/* Filter bar */}
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 12, alignItems: 'center' }}>
          <Space size={6}>
            <Text type="secondary" style={{ fontSize: 12 }}>Type:</Text>
            <Radio.Group
              size="small"
              value={typeFilter}
              onChange={e => setTypeFilter(e.target.value)}
              optionType="button"
              options={[
                { label: 'All', value: 'all' },
                { label: 'Happy Path', value: 'happy_path' },
                { label: 'Negative', value: 'negative' },
                { label: 'Edge Case', value: 'edge_case' },
                { label: 'Security', value: 'security' },
              ]}
            />
          </Space>
          <Space size={6}>
            <Text type="secondary" style={{ fontSize: 12 }}>Priority:</Text>
            <Radio.Group
              size="small"
              value={priorityFilter}
              onChange={e => setPriorityFilter(e.target.value)}
              optionType="button"
              options={[
                { label: 'All', value: 'all' },
                { label: 'Critical', value: 'critical' },
                { label: 'High', value: 'high' },
                { label: 'Medium', value: 'medium' },
                { label: 'Low', value: 'low' },
              ]}
            />
          </Space>
          {(typeFilter !== 'all' || priorityFilter !== 'all') && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              Showing {visibleCases.length} of {cases.length}
            </Text>
          )}
        </div>

        <Table
          dataSource={visibleCases}
          columns={columns}
          rowKey="id"
          pagination={visibleCases.length > 12 ? { pageSize: 12, size: 'small', showSizeChanger: false } : false}
          size="small"
          style={{ marginBottom: 16 }}
        />
        {incompleteApproved.length > 0 && (
          <div style={{ marginBottom: 8 }}>
            <Text type="warning" style={{ fontSize: 12 }}>
              {incompleteApproved.length} selected test case{incompleteApproved.length !== 1 ? 's have' : ' has'} no title or no steps — code generation may produce invalid tests.
            </Text>
          </div>
        )}
        <Button
          type="primary"
          icon={<PlayCircleOutlined />}
          disabled={approvedCount === 0}
          loading={loading}
          onClick={() => onApprove(cases)}
        >
          Generate Code for {approvedCount} test case{approvedCount !== 1 ? 's' : ''}
        </Button>
      </Card>

      {/* Regenerate modal */}
      <Modal
        title="Regenerate Test Cases"
        open={regenerateModalOpen}
        onOk={handleRegenerate}
        onCancel={() => setRegenerateModalOpen(false)}
        okText="Regenerate"
        confirmLoading={loading}
      >
        <Paragraph type="secondary" style={{ fontSize: 13 }}>
          Optionally describe what to improve, add, or change. Leave blank to regenerate without changes.
        </Paragraph>
        <TextArea
          rows={4}
          value={feedback}
          onChange={e => setFeedback(e.target.value)}
          placeholder="e.g. Add more edge cases for the password field. Include tests for session timeout."
          autoFocus
        />
      </Modal>

      {/* Full-edit modal */}
      <Modal
        title={editingCase ? `Edit: ${editingCase.title}` : ''}
        open={!!editingCase}
        onOk={saveEdit}
        onCancel={() => setEditingCase(null)}
        okText="Save"
        okButtonProps={{ icon: <SaveOutlined /> }}
        width={700}
        destroyOnClose
      >
        {editingCase && (
          <Form layout="vertical" size="small">
            <Form.Item label="Title">
              <Input
                value={editingCase.title}
                onChange={e => setEditField('title', e.target.value)}
              />
            </Form.Item>
            <Space style={{ width: '100%' }} size={12}>
              <Form.Item label="Type" style={{ flex: 1, minWidth: 130 }}>
                <Select
                  value={editingCase.type}
                  onChange={val => setEditField('type', val)}
                  options={[
                    { value: 'happy_path', label: 'Happy Path' },
                    { value: 'negative', label: 'Negative' },
                    { value: 'edge_case', label: 'Edge Case' },
                    { value: 'security', label: 'Security' },
                  ]}
                />
              </Form.Item>
              <Form.Item label="Priority" style={{ flex: 1, minWidth: 110 }}>
                <Select
                  value={editingCase.priority}
                  onChange={val => setEditField('priority', val)}
                  options={[
                    { value: 'critical', label: 'Critical' },
                    { value: 'high', label: 'High' },
                    { value: 'medium', label: 'Medium' },
                    { value: 'low', label: 'Low' },
                  ]}
                />
              </Form.Item>
            </Space>

            <Form.Item label="Preconditions">
              <Space direction="vertical" style={{ width: '100%' }} size={4}>
                {editingCase.preconditions.map((p, i) => (
                  <div key={i} style={{ display: 'flex', gap: 6 }}>
                    <Input
                      value={p}
                      onChange={e => updatePrecondition(i, e.target.value)}
                      placeholder={`Precondition ${i + 1}`}
                    />
                    <Button
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => removePrecondition(i)}
                    />
                  </div>
                ))}
                <Button type="dashed" icon={<PlusOutlined />} onClick={addPrecondition} size="small">
                  Add precondition
                </Button>
              </Space>
            </Form.Item>

            <Form.Item label="Steps">
              <Space direction="vertical" style={{ width: '100%' }} size={8}>
                {editingCase.steps.map((s, i) => (
                  <Card key={i} size="small" style={{ background: '#fafafa' }}
                    extra={
                      <Button type="text" danger icon={<DeleteOutlined />} size="small" onClick={() => removeStep(i)} />
                    }
                    title={<Text type="secondary" style={{ fontSize: 11 }}>Step {i + 1}</Text>}
                  >
                    <Form.Item label="Action" style={{ marginBottom: 6 }}>
                      <Input
                        value={s.action}
                        onChange={e => updateStep(i, 'action', e.target.value)}
                        placeholder="e.g. Enter valid username and password"
                      />
                    </Form.Item>
                    <Form.Item label="Expected Result" style={{ marginBottom: 0 }}>
                      <Input
                        value={s.expected_result}
                        onChange={e => updateStep(i, 'expected_result', e.target.value)}
                        placeholder="e.g. User is redirected to dashboard"
                      />
                    </Form.Item>
                  </Card>
                ))}
                <Button type="dashed" icon={<PlusOutlined />} onClick={addStep} size="small">
                  Add step
                </Button>
              </Space>
            </Form.Item>
          </Form>
        )}
      </Modal>
    </>
  )
}
