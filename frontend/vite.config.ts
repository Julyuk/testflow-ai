import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

const apiTarget = process.env.VITE_API_TARGET ?? 'http://localhost:8000'
const wsTarget = process.env.VITE_WS_TARGET ?? 'ws://localhost:8000'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true, ws: true },
    },
  },
  preview: {
    port: 5173,
    host: '0.0.0.0',
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true, ws: true },
    },
  },
})
