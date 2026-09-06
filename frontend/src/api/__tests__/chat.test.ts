import { afterEach, describe, expect, it, vi } from 'vitest'
import { streamChat } from '../chat'

function emptyStream(): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      controller.close()
    },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('api/chat streamChat 参数组装', () => {
  it('默认 kb_id=default / mode=dense，中文 question 正确编码，不带 conversation_id', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: emptyStream(),
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = streamChat({ question: '你好世界' }, { onEvent: vi.fn() })
    await client.done
    const url = fetchMock.mock.calls[0][0] as string
    expect(url.startsWith('/api/chat/stream?')).toBe(true)
    expect(url).toContain(`question=${encodeURIComponent('你好世界')}`)
    expect(url).toContain('kb_id=default')
    expect(url).toContain('mode=dense')
    expect(url).not.toContain('conversation_id')
  })

  it('传入 conversation_id / kbId / mode 时加入对应参数', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: emptyStream(),
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = streamChat(
      {
        question: 'q',
        conversationId: 'c_123',
        kbId: 'kb2',
        mode: 'hybrid',
      },
      { onEvent: vi.fn() },
    )
    await client.done
    const url = fetchMock.mock.calls[0][0] as string
    expect(url).toContain('conversation_id=c_123')
    expect(url).toContain('kb_id=kb2')
    expect(url).toContain('mode=hybrid')
  })
})
