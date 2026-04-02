import { Layout as AntLayout, Typography, Space } from 'antd'
import { ExperimentOutlined, SettingOutlined } from '@ant-design/icons'
import { Link, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'

const { Header, Content } = AntLayout
const { Title } = Typography

interface Props {
  children: ReactNode
}

export default function Layout({ children }: Props) {
  const location = useLocation()

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Header
        style={{
          display: 'flex',
          alignItems: 'center',
          background: '#001529',
          padding: '0 24px',
          gap: 12,
        }}
      >
        <ExperimentOutlined style={{ color: '#1677ff', fontSize: 22 }} />
        <Link to="/" style={{ textDecoration: 'none' }}>
          <Title level={4} style={{ color: '#fff', margin: 0, lineHeight: '64px' }}>
            TestFlow AI
          </Title>
        </Link>
        <Space style={{ marginLeft: 'auto' }} size="large">
          <Link
            to="/"
            style={{
              color: location.pathname === '/' ? '#1677ff' : 'rgba(255,255,255,0.65)',
              fontSize: 13,
            }}
          >
            Sessions
          </Link>
          <Link
            to="/settings"
            style={{
              color: location.pathname === '/settings' ? '#1677ff' : 'rgba(255,255,255,0.65)',
              fontSize: 13,
              display: 'flex',
              alignItems: 'center',
              gap: 4,
            }}
          >
            <SettingOutlined />
            Settings
          </Link>
        </Space>
      </Header>
      <Content style={{ padding: '24px', background: '#f5f5f5' }}>
        {children}
      </Content>
    </AntLayout>
  )
}
