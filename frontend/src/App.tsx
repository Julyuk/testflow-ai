import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import Layout from '@/components/common/Layout'
import HomePage from '@/pages/HomePage'
import PipelinePage from '@/pages/PipelinePage'
import SettingsPage from '@/pages/SettingsPage'

export default function App() {
  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: '#1677ff',
          borderRadius: 6,
        },
      }}
    >
      <BrowserRouter>
        <Layout>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/session/:sessionId" element={<PipelinePage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </Layout>
      </BrowserRouter>
    </ConfigProvider>
  )
}
