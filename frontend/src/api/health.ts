export interface HealthResponse {
  status: 'ok' | 'degraded'
  version: string
  components: Record<string, 'ok' | 'error'>
}

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch('/api/v1/health', {
    signal: AbortSignal.timeout(5000),
  })
  if (!response.ok) {
    throw new Error('Service unavailable')
  }
  const health = (await response.json()) as HealthResponse
  if (health.status !== 'ok') {
    throw new Error('Service unavailable')
  }
  return health
}
