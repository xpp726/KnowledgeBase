<script setup lang="ts">
// 文件预览弹窗：PDF（pdf.js 按页懒加载 + 加载进度）/ 图片 / TXT（自动识别 UTF-8/GBK）
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { previewBlob } from '../../api/documents'
import type { MixedFileNode } from '../../types/api'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

const props = defineProps<{
  modelValue: boolean
  doc: MixedFileNode | null
}>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

// ==================== 模式判定 ====================
const PDF_EXTS = new Set(['.pdf'])
const IMAGE_EXTS = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'])
const TEXT_EXTS = new Set(['.txt'])

const mode = computed<'pdf' | 'image' | 'text' | 'unsupported'>(() => {
  const ext = (props.doc?.file_ext ?? '').toLowerCase()
  if (PDF_EXTS.has(ext)) return 'pdf'
  if (IMAGE_EXTS.has(ext)) return 'image'
  if (TEXT_EXTS.has(ext)) return 'text'
  return 'unsupported'
})

const loading = ref(false)
const errorMsg = ref('')
const imgUrl = ref('')
const textContent = ref('')

// ==================== PDF 状态 ====================
const pdfProgress = ref(0) // 0~1，文件下载进度
const pdfTotal = ref(0)
const pdfContainerRef = ref<HTMLElement>()
let pdfDoc: pdfjs.PDFDocumentProxy | null = null
let rendering = false
let pendingPage = 1
let loadToken = 0

watch(
  () => [props.modelValue, props.doc?.doc_id] as const,
  async ([vis, docId]) => {
    if (vis && docId) await open()
  },
)

async function open() {
  const doc = props.doc
  if (!doc) return
  reset()
  loading.value = true
  errorMsg.value = ''
  try {
    const blob = await previewBlob(doc.doc_id)
    if (mode.value === 'image') {
      imgUrl.value = URL.createObjectURL(blob)
    } else if (mode.value === 'text') {
      textContent.value = await decodeText(blob)
    } else if (mode.value === 'pdf') {
      await loadPdf(blob)
    }
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : '预览加载失败'
  } finally {
    loading.value = false
  }
}

function reset() {
  loadToken += 1
  pdfDoc = null
  rendering = false
  pendingPage = 1
  pdfProgress.value = 0
  pdfTotal.value = 0
  pdfContainerRef.value?.scrollTo({ top: 0 })
  pdfContainerRef.value?.querySelectorAll('canvas').forEach((c) => c.remove())
  if (imgUrl.value) {
    URL.revokeObjectURL(imgUrl.value)
    imgUrl.value = ''
  }
  textContent.value = ''
  errorMsg.value = ''
}

// PDF：按页懒加载，滚动接近底部时渲染下一页
async function loadPdf(blob: Blob) {
  const token = ++loadToken
  const task = pdfjs.getDocument({ data: await blob.arrayBuffer() })
  task.onProgress = ({ loaded, total }) => {
    pdfProgress.value = total ? loaded / total : 0
  }
  pdfDoc = await task.promise
  if (token !== loadToken) return
  pdfTotal.value = pdfDoc.numPages
  pdfProgress.value = 1
  await nextTick() // 确保 pdf-container 已渲染
  await renderNext()
}

async function renderNext() {
  if (!pdfDoc || rendering || pendingPage > pdfDoc.numPages) return
  const token = loadToken
  rendering = true
  const n = pendingPage++
  try {
    const page = await pdfDoc.getPage(n)
    const viewport = page.getViewport({ scale: 1.4 })
    const canvas = document.createElement('canvas')
    canvas.width = viewport.width
    canvas.height = viewport.height
    canvas.className = 'pdf-page'
    await page.render({ canvas, viewport }).promise
    if (token !== loadToken) return
    pdfContainerRef.value?.appendChild(canvas)
    // 容器未被填满 → 继续渲染下一页（懒加载的核心：只渲染可视 + 邻近页）
    if (needMorePages()) {
      void renderNext()
    }
  } catch (e) {
    if (
      token === loadToken &&
      !(e instanceof Error && e.name === 'RenderingCancelledException')
    ) {
      errorMsg.value = 'PDF 渲染失败'
    }
  } finally {
    rendering = false
  }
}

function needMorePages(): boolean {
  const el = pdfContainerRef.value
  if (!el) return false
  return el.scrollTop + el.clientHeight >= el.scrollHeight - 300
}

function onPdfScroll() {
  if (needMorePages()) {
    void renderNext()
  }
}

// ==================== TXT 编码识别 ====================
async function decodeText(blob: Blob): Promise<string> {
  const buf = await blob.arrayBuffer()
  const utf8 = new TextDecoder('utf-8').decode(buf)
  if (utf8.includes('\uFFFD')) {
    try {
      return new TextDecoder('gbk').decode(buf)
    } catch {
      return utf8
    }
  }
  return utf8
}

onBeforeUnmount(() => {
  if (imgUrl.value) URL.revokeObjectURL(imgUrl.value)
})
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="doc?.file_name ?? '预览'"
    width="920"
    top="5vh"
    destroy-on-close
    append-to-body
    class="file-preview-dialog"
  >
    <div v-loading="loading" class="preview-body">
      <el-empty v-if="errorMsg" :description="errorMsg" />
      <template v-else-if="mode === 'pdf'">
        <div class="pdf-toolbar">
          <el-progress
            v-if="pdfProgress < 1"
            :percentage="Math.round(pdfProgress * 100)"
            :stroke-width="6"
          />
          <span v-else class="pdf-total">共 {{ pdfTotal }} 页 · 滚动加载</span>
        </div>
        <div ref="pdfContainerRef" class="pdf-container" @scroll="onPdfScroll"></div>
      </template>
      <div v-else-if="mode === 'image'" class="image-wrap">
        <img :src="imgUrl" :alt="doc?.file_name" />
      </div>
      <pre v-else-if="mode === 'text'" class="text-view">{{ textContent }}</pre>
      <el-empty v-else description="该文件类型暂不支持预览，可下载查看" />
    </div>
  </el-dialog>
</template>

<style scoped>
.preview-body {
  min-height: 320px;
}
.pdf-toolbar {
  padding: 2px 0 8px;
}
.pdf-total {
  font-size: 12px;
  color: #6b7280;
}
.pdf-container {
  max-height: 70vh;
  overflow-y: auto;
  background: #525659;
  border-radius: 4px;
  padding: 8px 0;
}
.pdf-page {
  display: block;
  width: auto;
  max-width: 100%;
  height: auto;
  margin: 0 auto 8px;
  background: #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.35);
}
.image-wrap {
  text-align: center;
  background: #525659;
  border-radius: 4px;
  padding: 8px;
  min-height: 320px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.image-wrap img {
  max-width: 100%;
  max-height: 70vh;
  border-radius: 2px;
}
.text-view {
  max-height: 70vh;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: Consolas, Menlo, Monaco, monospace;
  font-size: 13px;
  line-height: 1.6;
  background: #f7f7f5;
  border: 1px solid #e4e3dd;
  border-radius: 4px;
  padding: 12px;
  margin: 0;
}
</style>
