import { useState } from 'react'
import { Card, Form, Input, Button, Typography, Space, Alert } from 'antd'
import { QuestionCircleOutlined, SendOutlined, FastForwardOutlined } from '@ant-design/icons'

const { Title, Text } = Typography

interface Props {
  questions: string[]
  onSubmit: (answers: Record<string, string>) => Promise<void>
  loading?: boolean
}

export default function ClarificationPanel({ questions, onSubmit, loading }: Props) {
  const [answers, setAnswers] = useState<Record<string, string>>({})

  const handleSubmit = async () => {
    const allAnswered = questions.every(q => answers[q]?.trim())
    if (!allAnswered) return
    await onSubmit(answers)
  }

  const handleSkip = async () => {
    // Submit empty answers so the pipeline proceeds with what was already provided
    const emptyAnswers = Object.fromEntries(questions.map(q => [q, '']))
    await onSubmit(emptyAnswers)
  }

  const allAnswered = questions.every(q => answers[q]?.trim())

  return (
    <Card
      title={
        <Space>
          <QuestionCircleOutlined style={{ color: '#faad14' }} />
          <Title level={5} style={{ margin: 0 }}>
            Clarification Needed
          </Title>
        </Space>
      }
    >
      <Alert
        type="warning"
        message="The AI has some questions about your requirements. Answer them for better results, or skip to proceed with what was already provided."
        style={{ marginBottom: 16 }}
      />
      <Form layout="vertical">
        {questions.map((q, i) => (
          <Form.Item key={i} label={<Text strong>{q}</Text>}>
            <Input.TextArea
              rows={2}
              value={answers[q] ?? ''}
              onChange={e => setAnswers(prev => ({ ...prev, [q]: e.target.value }))}
              placeholder="Your answer..."
            />
          </Form.Item>
        ))}
        <Space>
          <Button
            type="primary"
            icon={<SendOutlined />}
            loading={loading}
            disabled={!allAnswered}
            onClick={handleSubmit}
          >
            Submit Answers
          </Button>
          <Button
            icon={<FastForwardOutlined />}
            loading={loading}
            onClick={handleSkip}
          >
            Skip / Proceed without clarifying
          </Button>
        </Space>
      </Form>
    </Card>
  )
}
