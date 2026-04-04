import { useEffect } from 'react'
import { useSessionStore } from '@/store/sessionStore'
import { useWebSocket } from './useWebSocket'

export function useSession(sessionId: string | null) {
  const { fetchPipelineState, fetchCheckpoints, fetchExecutions } = useSessionStore()

  useWebSocket(sessionId)

  useEffect(() => {
    if (!sessionId) return

    // Run all three fetches in parallel; errors are handled inside each action.
    Promise.all([
      fetchPipelineState(sessionId),
      fetchCheckpoints(sessionId),
      fetchExecutions(sessionId),
    ]).catch(() => {
      // Errors are stored in the session store and shown via the Alert in PipelinePage.
    })
  }, [sessionId, fetchPipelineState, fetchCheckpoints, fetchExecutions])
}
