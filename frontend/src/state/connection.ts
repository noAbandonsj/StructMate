import { reactive } from 'vue'
import { getHealth } from '../api/health'

export const serviceState = reactive({ status: 'checking' as 'checking' | 'connected' | 'disconnected' })
let revision = 0
let pending: Promise<void> | null = null

export function markServiceUnavailable() {
  revision++
  serviceState.status = 'disconnected'
}

export function checkService() {
  if (pending) return pending
  const stamp = revision
  pending = (async () => {
    try {
      await getHealth()
      if (stamp === revision) serviceState.status = 'connected'
    } catch {
      if (stamp === revision) serviceState.status = 'disconnected'
    } finally { pending = null }
  })()
  return pending
}
