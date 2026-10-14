export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export async function request<T>(path: string, options: RequestInit = {}, timeoutMs = 10000): Promise<T> {
  try {
    const response = await fetch('/api/v1' + path, {
      ...options,
      credentials: 'same-origin',
      cache: 'no-store',
      signal: options.signal
        ? AbortSignal.any([options.signal, AbortSignal.timeout(timeoutMs)])
        : AbortSignal.timeout(timeoutMs),
    })
    if (!response.ok) {
      const error = await response.json().catch(() => null) as {
        code?: string
        message?: string
      } | null
      throw new ApiError(
        response.status,
        error?.code ?? 'REQUEST_FAILED',
        error?.message ?? '操作失败，请稍后重试。',
      )
    }
    if (response.status === 204) return undefined as T
    return await response.json() as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    throw new ApiError(0, 'NETWORK_ERROR', '暂时无法连接服务，请稍后重试。')
  }
}
