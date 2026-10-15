import { reactive } from 'vue'

import * as api from '../api/auth'
import { ApiError } from '../api/client'
import { clearDrafts } from './learning-drafts'

export const authState = reactive<{
  status: 'loading' | 'ready' | 'error'
  account: api.AccountResponse | null
  error: string
  busy: boolean
}>({
  status: 'loading',
  account: null,
  error: '',
  busy: false,
})

let generation = 0
let pendingRestore: Promise<void> | null = null

function acceptAccount(account: api.AccountResponse | null) {
  const previous = authState.account?.user.id
  if (previous && previous !== account?.user.id) clearDrafts(previous)
  generation++
  authState.account = account
  authState.status = 'ready'
  authState.error = ''
}

export async function restoreAccount(force = false): Promise<void> {
  if (authState.status === 'ready' && !force) return
  if (pendingRestore) return pendingRestore
  const startedAt = generation
  authState.status = 'loading'
  const operation = (async () => {
    try {
      const account = await api.getAccount()
      if (startedAt === generation) acceptAccount(account)
    } catch (error) {
      if (startedAt !== generation) return
      if (error instanceof ApiError && error.status === 401) {
        acceptAccount(null)
      } else {
        authState.status = 'error'
        authState.error = error instanceof Error ? error.message : '无法恢复登录，请重试。'
      }
    }
  })()
  pendingRestore = operation
  try {
    await operation
  } finally {
    if (pendingRestore === operation) pendingRestore = null
  }
}

function beginMutation() {
  if (authState.busy) throw new Error('正在处理上一项操作，请稍候。')
  authState.busy = true
}

async function authenticate(action: () => Promise<api.AccountResponse>): Promise<void> {
  beginMutation()
  try {
    acceptAccount(await action())
  } finally {
    authState.busy = false
  }
}

export function signIn(data: api.Credentials): Promise<void> {
  return authenticate(() => api.login(data))
}

export function signUp(data: api.Registration): Promise<void> {
  return authenticate(() => api.register(data))
}

export async function signOut(): Promise<void> {
  beginMutation()
  try {
    await api.logout(authState.account?.csrf_token ?? '')
    acceptAccount(null)
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) acceptAccount(null)
    else throw error
  } finally {
    authState.busy = false
  }
}

export async function changeDisplayName(displayName: string): Promise<void> {
  const account = authState.account
  if (!account) throw new Error('请先登录。')
  beginMutation()
  const startedAt = generation
  try {
    const user = await api.updateProfile(displayName, account.csrf_token)
    if (startedAt === generation && authState.account?.user.id === user.id) {
      authState.account.user = user
    }
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) acceptAccount(null)
    throw error
  } finally {
    authState.busy = false
  }
}
