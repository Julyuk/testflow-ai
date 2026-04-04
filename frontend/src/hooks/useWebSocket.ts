import { useEffect, useRef } from 'react'
import type { WsEvent, ActivityLogEntry } from '@/types'
import { useSessionStore } from '@/store/sessionStore'

const MAX_RECONNECT_DELAY_MS = 30_000
const INITIAL_RECONNECT_DELAY_MS = 1_000

export function useWebSocket(sessionId: string | null) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectDelay = useRef(INITIAL_RECONNECT_DELAY_MS)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const unmounted = useRef(false)

  const applyStateUpdate = useSessionStore(s => s.applyStateUpdate)
  const applyExecutionDone = useSessionStore(s => s.applyExecutionDone)
  const appendExecutionOutput = useSessionStore(s => s.appendExecutionOutput)
  const appendActivityLog = useSessionStore(s => s.appendActivityLog)

  useEffect(() => {
    if (!sessionId) return
    unmounted.current = false

    function connect() {
      if (unmounted.current) return

      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const url = `${protocol}://${window.location.host}/api/pipeline/ws/${sessionId}`
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        // Reset backoff on successful connection
        reconnectDelay.current = INITIAL_RECONNECT_DELAY_MS
      }

      ws.onmessage = (ev) => {
        try {
          const event: WsEvent = JSON.parse(ev.data)
          if (event.type === 'stage_update') {
            applyStateUpdate(event.state)
          } else if (event.type === 'execution_done') {
            applyExecutionDone(event.result)
          } else if (event.type === 'execution_output') {
            appendExecutionOutput(event.line)
          } else if (event.type === 'activity_log') {
            const entry: ActivityLogEntry = {
              agent: event.agent,
              message: event.message,
              level: event.level as ActivityLogEntry['level'],
              timestamp: Date.now(),
            }
            appendActivityLog(entry)
          }
          // heartbeat: no-op
        } catch {
          // ignore parse errors
        }
      }

      ws.onclose = () => {
        if (unmounted.current) return
        // Reconnect with exponential backoff
        reconnectTimer.current = setTimeout(() => {
          reconnectDelay.current = Math.min(
            reconnectDelay.current * 2,
            MAX_RECONNECT_DELAY_MS,
          )
          connect()
        }, reconnectDelay.current)
      }

      ws.onerror = () => {
        // onclose will fire after onerror — reconnect handled there
        ws.close()
      }
    }

    connect()

    return () => {
      unmounted.current = true
      if (reconnectTimer.current !== null) {
        clearTimeout(reconnectTimer.current)
        reconnectTimer.current = null
      }
      wsRef.current?.close()
    }
  }, [sessionId, applyStateUpdate, applyExecutionDone, appendExecutionOutput, appendActivityLog])

  return wsRef
}
