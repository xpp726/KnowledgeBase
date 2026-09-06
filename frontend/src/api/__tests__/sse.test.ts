import { afterEach, describe, expect, it, vi } from 'vitest'
import { createSseClient, type SseError } from '../sse'

const enc = new TextEncoder()

function sseFrame(event: string, data: unknown): Uint8Array {
  return enc.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)
}

function streamFrom(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(c)
      controller.close()
    },
  })
}

/** 永不结束的流（用于 abort / 超时用例） */
function hangingStream(): ReadableStream<Uint8Array> {
  return new ReadableStream({ start() {} })
}

function concat(...arrs: Uint8Array[]): Uint8Array {
  const total = arrs.reduce((s, a) => s + a.length, 0)
  const out = new Uint8Array(total)
  let off = 0
  for (const a of arrs) {
    out.set(a, off)
    off += a.length
  }
  return out
}

function mockFetch(
  stream: ReadableStream<Uint8Array>,
  init?: { ok?: boolean; status?: number },
) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: init?.ok ?? true,
      status: init?.status ?? 200,
      body: stream,
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('api/sse 解析器', () => {
  it('① 标准事件序 meta→references→delta→done 逐帧分发', async () => {
    const events: Array<[string, unknown]> = []
    mockFetch(
      streamFrom([
        sseFrame('meta', { conversation_id: 'c1', is_new: true }),
        sseFrame('references', {
          sources: [
            {
              index: 1,
              chunk_id: 'k1',
              doc_id: 'd1',
              doc_name: 'a.md',
              page: 1,
              score: 0.9,
              text: 't',
            },
          ],
        }),
        sseFrame('delta', { content: '你' }),
        sseFrame('delta', { content: '好' }),
        sseFrame('done', {
          conversation_id: 'c1',
          message_id: 'm1',
          hit_count: 1,
          elapsed: 2.5,
          retrieval_ms: 100,
          llm_ms: 2400,
        }),
      ]),
    )
    const client = createSseClient('http://t/stream', {
      onEvent: (e, d) => events.push([e, d]),
    })
    await client.done
    expect(events.map(([e]) => e)).toEqual([
      'meta',
      'references',
      'delta',
      'delta',
      'done',
    ])
    expect((events[0][1] as { is_new: boolean }).is_new).toBe(true)
    expect((events[1][1] as { sources: unknown[] }).sources).toHaveLength(1)
    expect((events[4][1] as { llm_ms: number }).llm_ms).toBe(2400)
  })

  it('② 一帧跨多个 chunk（含帧分隔符 \n\n 被切开）时正确拼接', async () => {
    const events: unknown[] = []
    mockFetch(
      streamFrom([
        enc.encode('event: meta\ndata: {"conversation_id":"c1","is_new":false}\n\n'),
        enc.encode('event: delta\nd'),
        enc.encode('ata: {"content":"拼接"}\n'),
        enc.encode('\nevent: done\ndata: {"conversation_id":"c1","message_id":"m1","hit_count":0,"elapsed":1,"retrieval_ms":0,"llm_ms":0}\n\n'),
      ]),
    )
    const client = createSseClient('http://t/stream', {
      onEvent: (_e, d) => events.push(d),
    })
    await client.done
    expect(events).toHaveLength(3)
    expect((events[1] as { content: string }).content).toBe('拼接')
  })

  it('③ 半个中文字符跨 chunk：TextDecoder stream:true 不丢字不乱码', async () => {
    const events: unknown[] = []
    // "你" = E4 BD A0；在第一个汉字第 2 字节后切开
    const head = enc.encode('event: delta\ndata: {"content":"')
    const tail = enc.encode('"}\n\n')
    const bytes = enc.encode('你好')
    mockFetch(
      streamFrom([
        concat(head, bytes.slice(0, 1)),
        concat(bytes.slice(1), tail),
      ]),
    )
    const client = createSseClient('http://t/stream', {
      onEvent: (_e, d) => events.push(d),
    })
    await client.done
    expect((events[0] as { content: string }).content).toBe('你好')
  })

  it('④ 无 event 行时兜底为 message 事件', async () => {
    const events: string[] = []
    mockFetch(streamFrom([enc.encode('data: {"x":1}\n\n')]))
    const client = createSseClient('http://t/stream', {
      onEvent: (e) => events.push(e),
    })
    await client.done
    expect(events).toEqual(['message'])
  })

  it('⑤ HTTP 非 200 → onError({kind:"http", status})', async () => {
    mockFetch(hangingStream(), { ok: false, status: 500 })
    const onError = vi.fn()
    const client = createSseClient('http://t/stream', {
      onEvent: vi.fn(),
      onError,
    })
    await client.done
    expect(onError).toHaveBeenCalledWith({ kind: 'http', status: 500 })
  })

  it('⑥ abort → onError({kind:"aborted"}) 且不再分发任何事件', async () => {
    mockFetch(hangingStream())
    const onEvent = vi.fn()
    const onError = vi.fn()
    const client = createSseClient('http://t/stream', { onEvent, onError })
    client.abort()
    await client.done
    expect(onError).toHaveBeenCalledWith({ kind: 'aborted' })
    expect(onEvent).not.toHaveBeenCalled()
  })

  it('⑦ 超时（timeoutMs 内无任何数据）→ onError({kind:"timeout"})', async () => {
    mockFetch(hangingStream())
    const onError = vi.fn()
    const client = createSseClient(
      'http://t/stream',
      { onEvent: vi.fn(), onError },
      { timeoutMs: 50 },
    )
    await client.done
    expect(onError).toHaveBeenCalledWith({ kind: 'timeout' })
  })

  it('⑧ 网络异常（fetch reject）→ onError({kind:"network"})', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new TypeError('fetch failed')),
    )
    const onError = vi.fn()
    const client = createSseClient('http://t/stream', {
      onEvent: vi.fn(),
      onError,
    })
    await client.done
    expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'network' }) as SseError,
    )
  })
})
