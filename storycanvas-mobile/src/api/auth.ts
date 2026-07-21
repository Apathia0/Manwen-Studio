import { post, get, put } from '@/utils/request'
import type { AuthResponse, AuthUser, LoginRequest, RegisterRequest } from './types'

export function login(data: LoginRequest): Promise<AuthResponse> {
  return post<AuthResponse>('/api/auth/login', data)
}

export function register(data: RegisterRequest): Promise<AuthResponse> {
  return post<AuthResponse>('/api/auth/register', data)
}

export function logout(): Promise<void> {
  return post('/api/auth/logout')
}

export function getCurrentUser(): Promise<AuthUser> {
  return get<AuthUser>('/api/auth/me')
}

export function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  return put('/api/user/password', { old_password: oldPassword, new_password: newPassword })
}

export function sendEmailCode(email: string): Promise<void> {
  return post('/api/auth/forgot-password', { email })
}

export function forgotPassword(email: string): Promise<void> {
  return post('/api/auth/forgot-password', { email })
}

export function resetPassword(email: string, code: string, newPassword: string): Promise<void> {
  return post('/api/auth/reset-password', { email, verification_code: code, new_password: newPassword })
}
