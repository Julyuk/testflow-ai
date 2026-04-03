import { useEffect, useRef, useState } from 'react'
import { Card, Typography, Badge, Space } from 'antd'
import { LoadingOutlined, CheckCircleOutlined, WarningOutlined, CloseCircleOutlined, InfoCircleOutlined } from '@ant-design/icons'
import type { ActivityLogEntry } from '@/types'

const { Text } = Typography

// Static icon used for past info entries so they don't look "in progress"
const INFO_STATIC = <InfoCircleOutlined style={{ color: '#1677ff', fontSize: 11 }} />
const INFO_ACTIVE = <LoadingOutlined style={{ color: '#1677ff', fontSize: 11 }} />

const LEVEL_ICON: Record<string, React.ReactNode> = {
  success: <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 11 }} />,
  warning: <WarningOutlined style={{ color: '#faad14', fontSize: 11 }} />,
  error: <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 11 }} />,
}

const LEVEL_COLOR: Record<string, string> = {
  info: '#d6e4ff',
  success: '#f6ffed',
  warning: '#fffbe6',
  error: '#fff2f0',
}

const AGENT_COLORS: Record<string, string> = {
  orchestrator: '#722ed1',
  requirements_agent: '#1677ff',
  test_case_agent: '#13c2c2',
  test_generation_agent: '#2f54eb',
  validation_agent: '#52c41a',
  executor: '#fa8c16',
}

// Typewriter component — animates text character by character
function TypewriterText({ text, speed = 18 }: { text: string; speed?: number }) {
  const [displayed, setDisplayed] = useState('')
  const idxRef = useRef(0)

  useEffect(() => {
    idxRef.current = 0
    setDisplayed('')
    const interval = setInterval(() => {
      idxRef.current += 1
      setDisplayed(text.slice(0, idxRef.current))
      if (idxRef.current >= text.length) clearInterval(interval)
    }, speed)
    return () => clearInterval(interval)
  }, [text, speed])

  return <>{displayed}</>
}

interface Props {
  entries: ActivityLogEntry[]
  loading?: boolean
}

export default function AgentActivityLog({ entries, loading }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [entries.length])

  return (
    <Card
      size="small"
      title={
        <Space size={6}>
          <Text strong style={{ fontSize: 13 }}>Agent Activity</Text>
          {loading && <Badge status="processing" />}
        </Space>
      }
      style={{ marginTop: 16 }}
      bodyStyle={{ padding: 0 }}
    >
      <div
        style={{
          background: '#0d1117',
          borderRadius: '0 0 6px 6px',
          padding: '10px 14px',
          minHeight: 80,
          maxHeight: 260,
          overflowY: 'auto',
          fontFamily: '"Fira Code", "JetBrains Mono", Consolas, monospace',
        }}
      >
        {entries.length === 0 && (
          <Text style={{ color: '#484f58', fontSize: 12 }}>
            Waiting for pipeline to start...
          </Text>
        )}
        {entries.map((entry, i) => {
          const isLast = i === entries.length - 1
          const agentColor = AGENT_COLORS[entry.agent] ?? '#8b949e'
          const time = new Date(entry.timestamp).toLocaleTimeString('en', { hour12: false })
          // Show spinner only on the last info entry — past info entries get a static icon
          const icon = entry.level === 'info'
            ? (isLast ? INFO_ACTIVE : INFO_STATIC)
            : LEVEL_ICON[entry.level]
          return (
            <div
              key={i}
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: 8,
                marginBottom: 6,
                padding: '4px 6px',
                borderRadius: 4,
                background: isLast ? LEVEL_COLOR[entry.level] + '18' : 'transparent',
              }}
            >
              <Text style={{ color: '#484f58', fontSize: 10, marginTop: 2, minWidth: 60 }}>
                {time}
              </Text>
              {icon}
              <Text style={{ color: agentColor, fontSize: 11, minWidth: 120 }}>
                [{entry.agent}]
              </Text>
              <Text style={{ color: '#e6edf3', fontSize: 12, flex: 1 }}>
                {isLast ? <TypewriterText text={entry.message} /> : entry.message}
              </Text>
            </div>
          )
        })}
        <div ref={bottomRef} />
      </div>
    </Card>
  )
}
