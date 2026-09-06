// 知识库 API：列表 / 新建
import { http } from './http'
import type { KnowledgeBase, KnowledgeBaseCreate } from '../types/api'

export async function list(): Promise<KnowledgeBase[]> {
  const { data } = await http.get<KnowledgeBase[]>('/kbs')
  return data
}

export async function create(body: KnowledgeBaseCreate): Promise<KnowledgeBase> {
  const { data } = await http.post<KnowledgeBase>('/kbs', body)
  return data
}
