import { request } from './client'

export interface PublicUser {
  id: string
  username: string
  display_name: string
}

export interface AccountResponse {
  user: PublicUser
  default_knowledge_base: {
    id: string
    kind: 'personal'
    name: string
    is_readonly: boolean
  }
  csrf_token: string
}

export interface Credentials {
  username: string
  password: string
}

export interface Registration extends Credentials {
  display_name?: string
}

export function getAccount(): Promise<AccountResponse> {
  return request('/auth/me')
}

export function login(data: Credentials): Promise<AccountResponse> {
  return request('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function register(data: Registration): Promise<AccountResponse> {
  return request('/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function logout(csrfToken: string): Promise<void> {
  return request('/auth/logout', {
    method: 'POST',
    headers: { 'X-CSRF-Token': csrfToken },
  })
}

export function updateProfile(displayName: string, csrfToken: string): Promise<PublicUser> {
  return request('/auth/me', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
    body: JSON.stringify({ display_name: displayName }),
  })
}
