// 语音输入：对接 KB 后端 /api/asr/ws（WebSocket 代理 → ASR 实时识别）
//
// 链路：getUserMedia → MediaStreamTrackProcessor（原始采样率 PCM，绕过 AudioContext）
//   → float32→int16 → 聚包 200ms → WS binary
//   → KB 代理 → ASR 后端（服务端降采样 16k + VAD/ASR + 48k 高保真录音）
//
// 协议（与 ASR 项目一致）：start{binary, sample_rate} / stop ↔ status/partial/final/session_end/error
// 与 ASR 前端 useRecorder 的差异：目标 WS 走 KB 同源代理（生产可用）、
// 识别文本实时回填输入框（finals 拼接 + 当前句 partial）、静音 5s 自动停止、
// 支持取消（丢弃本次结果）。
import { onBeforeUnmount, ref } from 'vue'
import { useAuthStore } from '../stores/auth'

const WS_PATH = '/api/asr/ws'
const CHUNK_FRAMES = 9600 // 200ms @ 48kHz（聚包大小，后端 feed 接受任意大小）
const SILENT_MS = 5000 // 静音超过该时长自动停止（兜底，手动点停为主）
const SILENT_RMS = 0.05 // 单帧静音阈值（底噪抑制：环境底噪 RMS*4 常在 0.02~0.07 波动）
const SILENT_MIN_RATIO = 0.8 // 最近 5s 窗口内静音帧占比 ≥80% 视为静音（容忍底噪尖峰）
const CONNECT_TIMEOUT_MS = 5000
const STOP_WAIT_MS = 8000 // 发 stop 后等待 session_end 的超时兜底

interface VoiceMsg {
  type: string
  text?: string
  message?: string
}

export interface UseVoiceInputOptions {
  /** 识别文本变化回调（已确认句子 + 当前句 partial），用于回填输入框 */
  onText: (text: string) => void
}

export function useVoiceInput(opts: UseVoiceInputOptions) {
  const supported = ref(
    typeof navigator !== 'undefined' &&
      !!navigator.mediaDevices?.getUserMedia &&
      'MediaStreamTrackProcessor' in window &&
      typeof WebSocket !== 'undefined',
  )
  const recording = ref(false)
  const volume = ref(0) // 0-1 RMS（驱动波形动画）
  const elapsed = ref(0) // 录音时长（秒）
  const error = ref('')
  const autoStopped = ref(false) // 是否因静音自动停止（用于提示）
  const permissionDenied = ref(false) // 麦克风权限被拒绝（提示后禁用）

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const Processor: any = (window as any).MediaStreamTrackProcessor

  let ws: WebSocket | null = null
  let stream: MediaStream | null = null
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let reader: ReadableStreamDefaultReader<any> | null = null
  let detectedSR = 48000 // 检测到的硬件实际采样率
  let packBuf = new Int16Array(0)
  let finals: string[] = [] // 已确认句子（按序拼接为最终文本）
  let partial = '' // 当前句实时出字
  let timerId: number | null = null
  let silenceWindow: { t: number; s: boolean }[] = [] // 最近 5s 帧静音标志（窗口）
  let lastSilenceCheck = 0 // 静音判定节流
  let stopping = false // 停止流程中（防重复触发）
  let stopSent = false // stop 消息已发出：收尾 flush 的尾部 partial 属噪音，忽略
  let disposed = false

  const emitText = () => opts.onText(finals.join('') + partial)

  const stopTimer = () => {
    if (timerId !== null) {
      clearInterval(timerId)
      timerId = null
    }
  }

  /** 关闭 WS / 停止轨道 / 清缓冲（不修改状态） */
  const cleanupResources = () => {
    if (reader) {
      reader.cancel().catch(() => {})
      reader = null
    }
    if (stream) {
      stream.getTracks().forEach((t) => t.stop())
      stream = null
    }
    if (ws) {
      try {
        ws.onmessage = null
        ws.onclose = null
        ws.close()
      } catch {
        /* 忽略 */
      }
      ws = null
    }
    packBuf = new Int16Array(0)
  }

  /** 录音正式结束（session_end 或超时兜底）：状态复位 + 释放资源 */
  const finish = () => {
    if (timerId !== null) stopTimer()
    recording.value = false
    stopping = false
    cleanupResources()
  }

  /** 取消：直接断开，丢弃本次识别（调用方负责恢复输入框快照） */
  const cancel = () => {
    if (!recording.value) return
    stopping = true
    recording.value = false
    stopTimer()
    cleanupResources()
    stopping = false
  }

  const processFrame = (audioData: any) => {
    const frames = audioData.numberOfFrames
    const data = new Float32Array(frames)
    audioData.copyTo(data, { planeIndex: 0 })
    audioData.close()

    // float32 → int16 + RMS 音量
    const chunk = new Int16Array(frames)
    let rms = 0
    for (let i = 0; i < frames; i++) {
      const v = Math.max(-1, Math.min(1, data[i]))
      rms += v * v
      chunk[i] = v < 0 ? v * 0x8000 : v * 0x7fff
    }
    volume.value = Math.min(1, (frames > 0 ? Math.sqrt(rms / frames) : 0) * 4)

    // 静音检测：最近 SILENT_MS 窗口内静音帧占比 ≥ SILENT_MIN_RATIO → 自动停止
    // （窗口比例法容忍底噪尖峰，严格连续判定在底噪 0.02~0.07 波动时永不触发）
    const isSilent = volume.value < SILENT_RMS
    const now = performance.now()
    silenceWindow.push({ t: now, s: isSilent })
    while (silenceWindow.length && now - silenceWindow[0].t > SILENT_MS) silenceWindow.shift()
    if (!stopping && now - lastSilenceCheck >= 500) {
      lastSilenceCheck = now
      const total = silenceWindow.length
      if (total > 0 && now - silenceWindow[0].t >= SILENT_MS - 200) {
        let silentCount = 0
        for (const f of silenceWindow) if (f.s) silentCount++
        if (silentCount / total >= SILENT_MIN_RATIO) {
          autoStopped.value = true
          void stop()
        }
      }
    }

    // 聚包到 200ms 后整块发送，余量留在 packBuf
    const merged = new Int16Array(packBuf.length + chunk.length)
    merged.set(packBuf)
    merged.set(chunk, packBuf.length)
    packBuf = merged
    while (packBuf.length >= CHUNK_FRAMES && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(packBuf.slice(0, CHUNK_FRAMES).buffer)
      packBuf = packBuf.slice(CHUNK_FRAMES)
    }
  }

  const readLoop = async () => {
    while (reader && !disposed) {
      try {
        const { done, value } = await reader.read()
        if (done) break
        processFrame(value)
      } catch {
        break // reader 被取消或出错
      }
    }
  }

  const onMessage = (ev: MessageEvent) => {
    let m: VoiceMsg
    try {
      m = JSON.parse(ev.data as string)
    } catch {
      return
    }
    switch (m.type) {
      case 'partial':
        // stop 已发出：服务端收尾 flush 的尾部 partial（如尾音误识别）不再拼入
        if (stopSent) break
        partial = m.text ?? ''
        emitText()
        break
      case 'final':
        finals.push(m.text ?? '')
        partial = ''
        emitText()
        break
      case 'error':
        error.value = m.message || '语音识别服务错误'
        finish()
        break
      case 'session_end':
        finish()
        break
      default:
        break // status 等消息忽略
    }
  }

  const onClose = (ev: CloseEvent) => {
    if (stopping || !recording.value) return
    error.value =
      ev.code === 4401 ? '登录已过期，请重新登录' : '语音连接已断开，请重试'
    recording.value = false
    stopTimer()
    ws = null
  }

  /** 开始录音：清空既有识别结果 → 采流 → 连接代理 → start */
  const start = async () => {
    if (recording.value || !supported.value) return
    error.value = ''
    autoStopped.value = false
    stopping = false
    stopSent = false
    finals = []
    partial = ''
    packBuf = new Int16Array(0)
    silenceWindow = []
    lastSilenceCheck = 0
    elapsed.value = 0
    volume.value = 0

    const auth = useAuthStore()
    if (!auth.token) {
      error.value = '登录已过期，请重新登录'
      return
    }

    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
        },
      })
    } catch (e) {
      const err = e as { name?: string; message?: string }
      const name = err?.name ?? ''
      if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
        permissionDenied.value = true
        error.value = '麦克风权限被拒绝，无法使用语音输入'
      } else if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
        error.value = '未检测到麦克风设备，无法使用语音输入'
      } else {
        error.value = `无法访问麦克风：${err?.message ?? String(e)}`
      }
      return
    }

    try {
      const track = stream.getAudioTracks()[0]
      const processor = new Processor({ track })
      const r = processor.readable.getReader()
      reader = r

      // 读取第一帧获取硬件实际采样率（可能非 48k，如 44.1k）
      const first = await r.read()
      if (first.done) throw new Error('无法获取音频数据')
      detectedSR = first.value.sampleRate

      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(
        `${proto}://${location.host}${WS_PATH}?token=${encodeURIComponent(auth.token)}`,
      )
      ws.binaryType = 'arraybuffer'

      await new Promise<void>((resolve, reject) => {
        const onOpen = () => {
          clearTimeout(connectTimer)
          resolve()
        }
        const onErr = () => {
          clearTimeout(connectTimer)
          reject(new Error('语音服务连接失败（后端未启动？）'))
        }
        const connectTimer = setTimeout(() => {
          reject(new Error('语音服务连接超时'))
        }, CONNECT_TIMEOUT_MS)
        ws!.onopen = onOpen
        ws!.onerror = onErr
      })

      ws.onmessage = onMessage
      ws.onclose = onClose
      ws.send(JSON.stringify({ type: 'start', sample_rate: detectedSR }))

      // 处理第一帧 + 开始推流循环 + 计时
      processFrame(first.value)
      void readLoop()
      recording.value = true
      const startAt = Date.now()
      timerId = window.setInterval(() => {
        elapsed.value = Math.floor((Date.now() - startAt) / 1000)
      }, 500)
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
      cleanupResources()
    }
  }

  /** 手动停止：发残余音频 + stop，等待 session_end 收齐 final 后关闭 */
  const stop = () => {
    if (!recording.value || stopping) return
    stopping = true
    stopSent = true // 之后的 partial 一律忽略（保留 final）
    stopTimer()
    if (ws && ws.readyState === WebSocket.OPEN) {
      if (packBuf.length > 0) {
        ws.send(packBuf.buffer)
        packBuf = new Int16Array(0)
      }
      ws.send(JSON.stringify({ type: 'stop' }))
    }
    // 兜底：服务端无响应时强制结束（finals 已保留在输入框）
    window.setTimeout(() => {
      if (stopping) finish()
    }, STOP_WAIT_MS)
  }

  onBeforeUnmount(() => {
    disposed = true
    cancel()
  })

  return {
    supported,
    recording,
    volume,
    elapsed,
    error,
    autoStopped,
    permissionDenied,
    start,
    stop,
    cancel,
  }
}
