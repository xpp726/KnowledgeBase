// 会话 REST（与 backend/api/conversation.py 对齐）
import type { ChatMode, Conversation, Message, OkResponse } from '../types/api'
import { http } from './http'

export async function list(mode?: ChatMode): Promise<Conversation[]> {
  const { data } = await http.get<Conversation[]>('/conversations', {
    params: { kb_id: 'default', mode },
  })
  return data
}

export async function create(title = '', mode: ChatMode = 'kb'): Promise<Conversation> {
  const { data } = await http.post<Conversation>('/conversations', {
    kb_id: 'default',
    title,
    mode,
  })
  return data
}

export async function rename(id: string, title: string): Promise<Conversation> {
  const { data } = await http.patch<Conversation>(`/conversations/${id}`, {
    title,
  })
  return data
}

export async function remove(id: string): Promise<void> {
  await http.delete<OkResponse>(`/conversations/${id}`)
}

export async function messages(id: string): Promise<Message[]> {
  const { data } = await http.get<Message[]>(`/conversations/${id}/messages`)
  return data
}
