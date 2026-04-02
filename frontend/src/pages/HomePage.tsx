import { useEffect, useRef, useState } from 'react'
import {
  Card, Button, Table, Tag, Space, Typography, Modal,
  Form, Input, Tooltip, Popconfirm, Empty, Spin
} from 'antd'
import {
  PlusOutlined, PlayCircleOutlined, DeleteOutlined,
  ExperimentOutlined, ReloadOutlined, SyncOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useSessionStore } from '@/store/sessionStore'
import type { Session } from '@/types'

const { Title, Text } = Typography

const STATUS_COLOR: Record<string, string> = {
  created: 'default',
  running: 'processing',
  paused: 'warning',
  completed: 'success',
  error: 'error',
}

export default function HomePage() {
  const navigate = useNavigate()
  const {
    sessions, sessionsLoading,
    fetchSessions, createSession, deleteSession, setActiveSession,
  } = useSessionStore()

  const [modalOpen, setModalOpen] = useState(false)
  const [form] = Form.useForm()
  const [creating, setCreating] = useState(false)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    fetchSessions()
  }, [fetchSessions])

  // Auto-refresh every 8s while any session is running
  useEffect(() => {
    const hasRunning = sessions.some(s => s.status === 'running')
    if (hasRunning && !intervalRef.current) {
      intervalRef.current = setInterval(() => fetchSessions(), 8000)
    } else if (!hasRunning && intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [sessions, fetchSessions])

  const handleCreate = async () => {
    const values = await form.validateFields()
    setCreating(true)
    try {
      const session = await createSession(
        values.name,
        values.description ?? '',
        values.target_url ?? 'https://www.saucedemo.com'
      )
      form.resetFields()
      setModalOpen(false)
      setActiveSession(session)
      navigate(`/session/${session.id}`)
    } finally {
      setCreating(false)
    }
  }

  const handleOpen = (session: Session) => {
    setActiveSession(session)
    navigate(`/session/${session.id}`)
  }

  const columns = [
    {
      title: 'Name',
      dataIndex: 'name',
      render: (name: string, record: Session) => (
        <Button type="link" onClick={() => handleOpen(record)} style={{ padding: 0 }}>
          {name}
        </Button>
      ),
    },
    {
      title: 'Target URL',
      dataIndex: 'target_url',
      render: (url: string) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {url}
        </Text>
      ),
    },
    {
      title: 'Stage',
      dataIndex: 'current_stage',
      render: (stage: string) => (
        <Text code style={{ fontSize: 12 }}>
          {stage}
        </Text>
      ),
    },
    {
      title: 'Status',
      dataIndex: 'status',
      render: (status: string) => (
        <Tag color={STATUS_COLOR[status] ?? 'default'}>{status}</Tag>
      ),
    },
    {
      title: 'Created',
      dataIndex: 'created_at',
      render: (ts: string) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {new Date(ts).toLocaleString()}
        </Text>
      ),
    },
    {
      title: '',
      key: 'actions',
      width: 110,
      render: (_: unknown, record: Session) => (
        <Space>
          <Tooltip title={record.status === 'error' ? 'Open to restart' : 'Open pipeline'}>
            <Button
              size="small"
              icon={record.status === 'error' ? <ReloadOutlined /> : <PlayCircleOutlined />}
              danger={record.status === 'error'}
              onClick={() => handleOpen(record)}
            />
          </Tooltip>
          <Popconfirm
            title="Delete this session?"
            description="This will permanently delete all pipeline data."
            onConfirm={() => deleteSession(record.id)}
            okText="Delete"
            okButtonProps={{ danger: true }}
          >
            <Tooltip title="Delete session">
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 20, gap: 12 }}>
        <ExperimentOutlined style={{ fontSize: 28, color: '#1677ff' }} />
        <div>
          <Title level={3} style={{ margin: 0 }}>TestFlow AI</Title>
          <Text type="secondary">AI-powered automated testing pipeline</Text>
        </div>
        <Space style={{ marginLeft: 'auto' }}>
          <Tooltip title="Refresh sessions">
            <Button
              icon={<SyncOutlined spin={sessionsLoading} />}
              onClick={() => fetchSessions()}
              loading={sessionsLoading}
            />
          </Tooltip>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setModalOpen(true)}
          >
            New Session
          </Button>
        </Space>
      </div>

      <Card>
        {sessionsLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin size="large" />
          </div>
        ) : sessions.length === 0 ? (
          <Empty
            description="No test sessions yet"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          >
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
              Create First Session
            </Button>
          </Empty>
        ) : (
          <Table
            dataSource={sessions}
            columns={columns}
            rowKey="id"
            pagination={{ pageSize: 15 }}
            size="middle"
          />
        )}
      </Card>

      <Modal
        title="New Test Session"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleCreate}
        okText="Create & Open"
        confirmLoading={creating}
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="name"
            label="Session Name"
            rules={[{ required: true, message: 'Required' }]}
          >
            <Input placeholder="e.g. SauceDemo Login Tests" />
          </Form.Item>
          <Form.Item name="description" label="Description">
            <Input placeholder="Optional description" />
          </Form.Item>
          <Form.Item name="target_url" label="Target Application URL">
            <Input placeholder="https://www.saucedemo.com" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
