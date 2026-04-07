import { useEffect, useState } from 'react'
import {
  Card, Form, Input, Button, Typography, Space, Alert,
  Divider, Tag, Popconfirm, message
} from 'antd'
import {
  SaveOutlined, DeleteOutlined, CheckCircleOutlined, ApiOutlined
} from '@ant-design/icons'
import { integrationsApi } from '@/api/client'
import type { AzureDevOpsConfig } from '@/types'

const { Title, Text } = Typography

export default function SettingsPage() {
  const [azureForm] = Form.useForm()
  const [azureConfig, setAzureConfig] = useState<AzureDevOpsConfig | null>(null)
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    integrationsApi.getAzureConfig()
      .then(config => {
        setAzureConfig(config)
        if (config.configured) {
          azureForm.setFieldsValue({
            organization: config.organization,
            project: config.project,
          })
        }
      })
      .finally(() => setLoading(false))
  }, [azureForm])

  const handleSaveAzure = async () => {
    const values = await azureForm.validateFields()
    setSaving(true)
    try {
      await integrationsApi.saveAzureConfig(values.organization, values.project, values.pat)
      const updated = await integrationsApi.getAzureConfig()
      setAzureConfig(updated)
      message.success('Azure DevOps configuration saved')
      azureForm.setFieldValue('pat', '')
    } catch {
      message.error('Failed to save configuration')
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteAzure = async () => {
    await integrationsApi.deleteAzureConfig()
    setAzureConfig({ configured: false })
    azureForm.resetFields()
    message.success('Azure DevOps configuration removed')
  }

  return (
    <div style={{ maxWidth: 720, margin: '0 auto' }}>
      <Title level={4} style={{ marginBottom: 24 }}>Settings</Title>

      {/* Azure DevOps */}
      <Card
        title={
          <Space>
            <ApiOutlined style={{ color: '#0078d4' }} />
            <Text strong>Azure DevOps Integration</Text>
            {azureConfig?.configured && (
              <Tag color="green" icon={<CheckCircleOutlined />}>Connected</Tag>
            )}
          </Space>
        }
        loading={loading}
      >
        {azureConfig?.configured && (
          <Alert
            type="success"
            message={
              <Space>
                <Text>Connected to</Text>
                <Text code>{azureConfig.organization}</Text>
                <Text>/</Text>
                <Text code>{azureConfig.project}</Text>
              </Space>
            }
            style={{ marginBottom: 16 }}
          />
        )}

        <Form form={azureForm} layout="vertical">
          <Form.Item
            name="organization"
            label="Organization"
            rules={[{ required: true, message: 'Required' }]}
            extra="Your Azure DevOps organization name (e.g. mycompany)"
          >
            <Input placeholder="mycompany" />
          </Form.Item>
          <Form.Item
            name="project"
            label="Project"
            rules={[{ required: true, message: 'Required' }]}
            extra="The project where test plans will be created"
          >
            <Input placeholder="MyProject" />
          </Form.Item>
          <Form.Item
            name="pat"
            label={azureConfig?.configured ? 'New Personal Access Token (leave blank to keep current)' : 'Personal Access Token'}
            rules={azureConfig?.configured ? [] : [{ required: true, message: 'Required' }]}
            extra={
              <Text type="secondary" style={{ fontSize: 11 }}>
                PAT is encrypted with AES-128 (Fernet) before storage.
                Required scopes: Work Items (Read & Write), Test Plans (Read & Write).
              </Text>
            }
          >
            <Input.Password placeholder={azureConfig?.configured ? azureConfig.pat : 'your-pat-token'} />
          </Form.Item>

          <Space>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              onClick={handleSaveAzure}
              loading={saving}
            >
              Save Configuration
            </Button>
            {azureConfig?.configured && (
              <Popconfirm
                title="Remove Azure DevOps configuration?"
                onConfirm={handleDeleteAzure}
                okButtonProps={{ danger: true }}
              >
                <Button danger icon={<DeleteOutlined />}>
                  Remove
                </Button>
              </Popconfirm>
            )}
          </Space>
        </Form>

        <Divider />

        <Title level={5}>What this enables</Title>
        <ul style={{ paddingLeft: 20 }}>
          <li><Text>Sync generated test cases as Work Items to Azure DevOps Test Plans</Text></li>
          <li><Text>Trigger Azure Pipelines CI/CD runs from the pipeline page</Text></li>
          <li><Text>Download pre-configured <Text code>azure-pipelines.yml</Text> from the code viewer</Text></li>
        </ul>
      </Card>

      <Card
        title={
          <Space>
            <ApiOutlined />
            <Text strong>GitHub Actions</Text>
          </Space>
        }
        style={{ marginTop: 16 }}
      >
        <Text type="secondary">
          No configuration required. After code generation, use the <Text code>Export → GitHub Actions workflow</Text> button
          in the code viewer to download a <Text code>.github/workflows/tests.yml</Text> file tailored
          to your session's generated tests and target URL.
        </Text>
      </Card>
    </div>
  )
}
