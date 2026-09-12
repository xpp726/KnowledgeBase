<script setup lang="ts">
// 输入区：模式下拉（通用/知识库）+ 语音输入（ASR 实时流式出字）+ 发送/停止切换
// Enter 发送、Shift+Enter 换行、中文输入法组合期不触发
// 语音输入：话筒按钮在输入框内右侧；开始录音清空输入框（识别文字独占、只读），
// 手动点停或静音 5s 自动停止；取消丢弃本次识别并恢复录音前内容；识别完可编辑后再发送。
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'
import { useChatStore } from '../../stores/chat'
import { useVoiceInput } from '../../composables/useVoiceInput'
import type { ChatMode } from '../../types/api'

const store = useChatStore()
const { streamState, currentMode } = storeToRefs(store)
const text = ref('')

const busy = computed(
  () => streamState.value === 'connecting' || streamState.value === 'streaming',
)

// ==================== 语音输入 ====================
// useVoiceInput 返回的是普通对象，其中的 ref 需解构到顶层，模板才能自动解包
const voice = useVoiceInput({
  onText: (t) => {
    text.value = t
  },
})
const voiceRecording = voice.recording
const voiceSupported = voice.supported
const voicePermissionDenied = voice.permissionDenied
const voiceElapsed = voice.elapsed
const voiceVolume = voice.volume
const voiceError = voice.error
const voiceAutoStopped = voice.autoStopped

const voiceSnapshot = ref('') // 录音前输入框内容（取消时恢复）
let voiceWarned = false // 启动失败提示只弹一次

// 降级：问答生成中 / 浏览器不支持 / 麦克风权限被拒 → 禁用话筒
const voiceDisabled = computed(
  () => busy.value || !voiceSupported.value || voicePermissionDenied.value,
)

async function onToggleVoice() {
  if (voiceRecording.value) {
    voice.stop()
    return
  }
  if (voiceDisabled.value) return
  // 开始录音：保存快照 + 清空输入框，识别文字独占
  voiceSnapshot.value = text.value
  text.value = ''
  await voice.start()
  if (!voiceRecording.value) {
    // 启动失败（权限/连接）：恢复录音前内容
    text.value = voiceSnapshot.value
  }
  if (voiceError.value && !voiceWarned) {
    voiceWarned = true
    ElMessage.warning(voiceError.value)
  }
}

function onCancelVoice() {
  voice.cancel()
  text.value = voiceSnapshot.value // 丢弃识别结果，恢复录音前内容
}

// 静音自动停止提示
watch(voiceAutoStopped, (v) => {
  if (v) ElMessage.info('检测到静音，已自动停止录音')
})

// 波形条：真实音量驱动（5 根，不同系数制造起伏感）
const waveBars = computed(() => {
  const v = voiceVolume.value
  const amp = Math.max(0.06, v)
  return [1, 1.4, 1.1, 1.6, 0.9].map((k) => {
    const h = Math.min(100, Math.round(amp * 70 * k))
    return `${h}%`
  })
})

const timerText = computed(() => {
  const s = voiceElapsed.value
  const m = Math.floor(s / 60)
    .toString()
    .padStart(2, '0')
  const ss = (s % 60).toString().padStart(2, '0')
  return `${m}:${ss}`
})

const sendDisabled = computed(
  () => busy.value || voiceRecording.value || !text.value.trim(),
)

// ==================== 发送 / 停止 ====================
function onModeChange(mode: ChatMode) {
  void store.switchMode(mode)
}

function onSend() {
  const q = text.value.trim()
  if (!q || busy.value || voiceRecording.value) return
  void store.sendMessage(q)
  text.value = ''
}

function onStop() {
  store.stopGeneration()
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    onSend()
  }
}
</script>

<template>
  <div class="chat-input-bar">
    <div class="chat-input-wrap">
      <el-select
        :model-value="currentMode"
        class="mode-select"
        :disabled="busy"
        @change="onModeChange"
      >
        <el-option label="知识库问答" value="kb" />
        <el-option label="通用问答" value="general" />
      </el-select>
      <div class="voice-input">
        <el-input
          v-model="text"
          type="textarea"
          :autosize="{ minRows: 3, maxRows: 6 }"
          :disabled="busy"
          :readonly="voiceRecording"
          placeholder="输入问题，Enter 发送，Shift+Enter 换行"
          resize="none"
          @keydown="onKeydown"
        />
        <!-- 输入框内右侧：语音控制区 -->
        <div class="voice-controls">
          <template v-if="voiceRecording">
            <span class="voice-wave" aria-hidden="true">
              <i v-for="(h, i) in waveBars" :key="i" :style="{ height: h }" />
            </span>
            <span class="voice-timer">{{ timerText }}</span>
            <el-icon
              class="voice-cancel"
              title="取消录音（丢弃本次识别）"
              @click="onCancelVoice"
            >
              <Close />
            </el-icon>
            <el-icon
              class="voice-mic active"
              title="停止并保留识别文字"
              @click="onToggleVoice"
            >
              <Mic />
            </el-icon>
          </template>
          <el-icon
            v-else
            class="voice-mic"
            :class="{ disabled: voiceDisabled }"
            :title="
              !voiceSupported
                ? '当前浏览器不支持语音输入'
                : voicePermissionDenied
                  ? '麦克风权限被拒绝，已禁用语音输入'
                  : '语音输入'
            "
            @click="onToggleVoice"
          >
            <Mic />
          </el-icon>
        </div>
      </div>
      <div class="input-actions">
        <el-button v-if="busy" type="danger" plain @click="onStop">
          <el-icon><VideoPause /></el-icon>
          <span>停止生成</span>
        </el-button>
        <el-button v-else type="primary" :disabled="sendDisabled" @click="onSend">
          <el-icon><Promotion /></el-icon>
          <span>发送</span>
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-input-bar {
  border-top: 1px solid var(--border);
  background: var(--card);
  padding: 12px 24px 16px;
}

.chat-input-wrap {
  max-width: 960px;
  margin: 0 auto;
  display: flex;
  gap: 10px;
  align-items: flex-end;
}

.mode-select {
  flex-shrink: 0;
  width: 128px;
  padding-bottom: 2px;
}

.mode-select :deep(.el-select__wrapper) {
  min-height: 32px;
  border-radius: 8px;
}

/* 输入框容器：话筒按钮绝对定位在内部右侧 */
.voice-input {
  position: relative;
  flex: 1;
}

/* 输入框高度平滑过渡（默认 3 行 → 最多 6 行） */
.voice-input :deep(.el-textarea__inner) {
  transition: height 0.15s ease;
  padding-right: 72px; /* 给输入框内右侧的语音控制区留空间 */
}

.voice-controls {
  position: absolute;
  right: 10px;
  bottom: 9px;
  display: flex;
  align-items: center;
  gap: 8px;
  z-index: 1;
  pointer-events: none;
}

.voice-controls > * {
  pointer-events: auto;
}

.voice-mic {
  cursor: pointer;
  font-size: 18px;
  color: var(--el-text-color-secondary);
  transition: color 0.2s;
}

.voice-mic:hover:not(.disabled) {
  color: var(--el-color-primary);
}

.voice-mic.active {
  color: #e5484d;
  animation: voice-pulse 1.2s ease-in-out infinite;
}

.voice-mic.disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

.voice-cancel {
  cursor: pointer;
  font-size: 14px;
  color: var(--el-text-color-secondary);
}

.voice-cancel:hover {
  color: #e5484d;
}

.voice-timer {
  font-size: 12px;
  color: #e5484d;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

/* 真实音量波形：5 根条，高度由麦克风 RMS 驱动 */
.voice-wave {
  display: inline-flex;
  align-items: flex-end;
  gap: 2px;
  height: 16px;
}

.voice-wave i {
  width: 3px;
  border-radius: 2px;
  background: #e5484d;
  transition: height 0.12s ease;
}

@keyframes voice-pulse {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.12);
  }
}

.input-actions {
  flex-shrink: 0;
  padding-bottom: 2px;
}
</style>
