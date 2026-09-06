// 手写 SSE 解析器（fetch + ReadableStream，零依赖）
//
// 设计要点（见 docs/前端实现方案.md §5）：
// - 不自动重连：本端点是有副作用的 GET（落库 user 消息），任何终局后由 UI 手动重试
// - abort / 超时 / 错误码全由 fetch 原生能力覆盖
// - 帧格式：event: X\ndata: JSON\n\n（后端 ensure_ascii=False 单行 data）
// - TextDecoder stream:true：中文字符被 TCP 分片截断时跨 chunk 正确拼接

export type SseErrorKind = 'http' | 'network' | 'timeout' | 'aborted' | 'parse'

export interface SseError {
  kind: SseErrorKind
  status?: number
  message?: string
}

export interface SseHandlers {
  onOpen?: () => void
  onEvent: (event: string, data: unknown) => void
  onClose?: () => void
  onError?: (err: SseError) => void
}

export interface SseClient {
  abort(): void
  readonly done: Promise<void>
}

export interface SseOptions {
  timeoutMs?: number
  signal?: AbortSignal
  headers?: Record<string, string>
}

export function createSseClient(
  url: string,
  handlers: SseHandlers,
  opts: SseOptions = {},
): SseClient {
  const timeoutMs = opts.timeoutMs ?? 60_000
  const controller = new AbortController()
  let settled = false
  let timedOut = false
  let buffer = ''
  let timer: ReturnType<typeof setTimeout> | null = null

  let resolveDone!: () => void
  const done = new Promise<void>((resolve) => {
    resolveDone = resolve
  })

  const clearTimer = () => {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
  }

  // 所有终局（正常结束 / 各种失败）统一收敛于此；settled 保证只触发一次
  const settle = (err: SseError | null) => {
    if (settled) return
    settled = true
    clearTimer()
    if (err) handlers.onError?.(err)
    else handlers.onClose?.()
    resolveDone()
  }

  // 超时：从 fetch 发出起，60s 内无任何新字节即判定超时；每次收到数据重置
  const armTimer = () => {
    clearTimer()
    timer = setTimeout(() => {
      timedOut = true
      controller.abort()
      settle({ kind: 'timeout' })
    }, timeoutMs)
  }

  const parseFrame = (raw: string) => {
    if (settled) return
    let eventName = 'message'
    let data = ''
    for (const line of raw.split('\n')) {
      if (line.startsWith('event:')) {
        eventName = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        const val = line.slice(5)
        data += data === '' ? val : `\n${val}`
      }
      // 注释行 / 空行直接忽略
    }
    if (data === '') return
    try {
      handlers.onEvent(eventName, JSON.parse(data))
    } catch {
      settle({ kind: 'parse', message: `invalid JSON in event "${eventName}"` })
    }
  }

  const dispatchFrames = () => {
    while (!settled) {
      const idx = buffer.indexOf('\n\n')
      if (idx === -1) break
      const raw = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      parseFrame(raw)
    }
  }

  const run = async () => {
    try {
      armTimer()
      const res = await fetch(url, { signal: controller.signal, headers: opts.headers })
      if (settled) return
      if (!res.ok) {
        settle({ kind: 'http', status: res.status })
        return
      }
      handlers.onOpen?.()
      const reader = res.body?.getReader()
      if (!reader) {
        settle({ kind: 'network', message: 'response has no body' })
        return
      }
      const decoder = new TextDecoder('utf-8')
      for (;;) {
        const { done: eof, value } = await reader.read()
        if (settled) return
        if (eof) break
        armTimer()
        buffer += decoder.decode(value, { stream: true })
        dispatchFrames()
      }
      decoder.decode() // 冲刷尾部残余（无 \n\n 的半帧在 EOF 时本就无效，丢弃）
      settle(null)
    } catch (err) {
      if (settled) return
      if (err instanceof DOMException && err.name === 'AbortError') {
        settle(timedOut ? { kind: 'timeout' } : { kind: 'aborted' })
      } else {
        settle({ kind: 'network', message: (err as Error)?.message })
      }
    }
  }

  void run()

  const abort = () => {
    if (settled) return
    controller.abort()
    settle({ kind: 'aborted' })
  }

  if (opts.signal) {
    if (opts.signal.aborted) {
      abort()
    } else {
      opts.signal.addEventListener('abort', abort, { once: true })
    }
  }

  return { abort, done }
}
