import { useEffect, useState } from 'react'
import {
  Card, Form, Input, Button, Typography, Space, Alert,
  Divider, Tag, Popconfirm, message
} from 'antd'
import {
  SaveOutlined, DeleteOutlined, CheckCircleOutlined, ApiOutlined, GithubOutlined
} from '@ant-design/icons'
import { integrationsApi, githubApi } from '@/api/client'
import type { AzureDevOpsConfig, GitHubConfig } from '@/types'

const { Title, Text } = Typography

export default function SettingsPage() {
  const [azureForm] = Form.useForm()
  const [azureConfig, setAzureConfig] = useState<AzureDevOpsConfig | null>(null)
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)

  const [githubForm] = Form.useForm()
  const [githubConfig, setGithubConfig] = useState<GitHubConfig | null>(null)
  const [githubSaving, setGithubSaving] = useState(false)
  const [githubLoading, setGithubLoading] = useState(true)

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

  useEffect(() => {
    githubApi.getConfig()
      .then(config => {
        setGithubConfig(config)
        if (config.configured) {
          githubForm.setFieldsValue({
            owner: config.owner,
            repo: config.repo,
            branch: config.branch ?? 'main',
          })
        }
      })
      .finally(() => setGithubLoading(false))
  }, [githubForm])

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

  const handleSaveGitHub = async () => {
    const values = await githubForm.validateFields()
    setGithubSaving(true)
    try {
      await githubApi.saveConfig(values.owner, values.repo, values.token, values.branch ?? 'main')
      const updated = await githubApi.getConfig()
      setGithubConfig(updated)
      message.success('GitHub configuration saved')
      githubForm.setFieldValue('token', '')
    } catch {
      message.error('Failed to save GitHub configuration')
    } finally {
      setGithubSaving(false)
    }
  }

  const handleDeleteGitHub = async () => {
    await githubApi.deleteConfig()
    setGithubConfig({ configured: false })
    githubForm.resetFields()
    message.success('GitHub configuration removed')
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
            <GithubOutlined />
            <Text strong>GitHub Integration</Text>
            {githubConfig?.configured && (
              <Tag color="green" icon={<CheckCircleOutlined />}>Connected</Tag>
            )}
          </Space>
        }
        loading={githubLoading}
        style={{ marginTop: 16 }}
      >
        {githubConfig?.configured && (
          <Alert
            type="success"
            message={
              <Space>
                <Text>Connected to</Text>
                <Text code>{githubConfig.owner}/{githubConfig.repo}</Text>
                <Text type="secondary">branch: {githubConfig.branch}</Text>
              </Space>
            }
            style={{ marginBottom: 16 }}
          />
        )}

        <Form form={githubForm} layout="vertical">
          <Form.Item
            name="owner"
            label="Owner"
            rules={[{ required: true, message: 'Required' }]}
            extra="GitHub username or organization (e.g. mycompany)"
          >
            <Input placeholder="mycompany" />
          </Form.Item>
          <Form.Item
            name="repo"
            label="Repository"
            rules={[{ required: true, message: 'Required' }]}
            extra="Repository name where tests will be pushed"
          >
            <Input placeholder="my-tests-repo" />
          </Form.Item>
          <Form.Item
            name="branch"
            label="Branch"
            extra="Target branch (default: main)"
          >
            <Input placeholder="main" />
          </Form.Item>
          <Form.Item
            name="token"
            label={githubConfig?.configured ? 'New Personal Access Token (leave blank to keep current)' : 'Personal Access Token'}
            rules={githubConfig?.configured ? [] : [{ required: true, message: 'Required' }]}
            extra={
              <Text type="secondary" style={{ fontSize: 11 }}>
                PAT is encrypted with AES-128 (Fernet) before storage.
                Required scopes: Contents (Read & Write).
              </Text>
            }
          >
            <Input.Password placeholder={githubConfig?.configured ? githubConfig.token : 'ghp_...'} />
          </Form.Item>

          <Space>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              onClick={handleSaveGitHub}
              loading={githubSaving}
            >
              Save Configuration
            </Button>
            {githubConfig?.configured && (
              <Popconfirm
                title="Remove GitHub configuration?"
                onConfirm={handleDeleteGitHub}
                okButtonProps={{ danger: true }}
              >
                <Button danger icon={<DeleteOutlined />}>Remove</Button>
              </Popconfirm>
            )}
          </Space>
        </Form>

        <Divider />

        <Title level={5}>What this enables</Title>
        <ul style={{ paddingLeft: 20 }}>
          <li><Text>Push generated test files directly to a GitHub repository</Text></li>
          <li><Text>Download a pre-configured <Text code>.github/workflows/tests.yml</Text> from the code viewer</Text></li>
        </ul>
      </Card>
    </div>
  )
}
