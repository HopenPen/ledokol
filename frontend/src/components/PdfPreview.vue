<script setup lang="ts">
import { GlobalWorkerOptions, getDocument, type PDFDocumentLoadingTask, type PDFDocumentProxy, type RenderTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps<{ url: string; filename: string }>()
GlobalWorkerOptions.workerSrc = workerUrl
const canvas = ref<HTMLCanvasElement | null>(null)
const page = ref(1)
const pages = ref(0)
const busy = ref(true)
const error = ref('')
let pdf: PDFDocumentProxy | null = null
let loading: PDFDocumentLoadingTask | null = null
let rendering: RenderTask | null = null
let disposed = false

async function renderPage() {
  if (!pdf || !canvas.value || disposed) return
  busy.value = true
  error.value = ''
  try {
    const documentPage = await pdf.getPage(page.value)
    if (disposed || !canvas.value) return
    const width = Math.min(canvas.value.parentElement?.clientWidth ?? 900, 1200) - 32
    const viewport = documentPage.getViewport({ scale: Math.max(0.2, width / documentPage.getViewport({ scale: 1 }).width) })
    const ratio = Math.min(window.devicePixelRatio || 1, 2)
    canvas.value.width = Math.ceil(viewport.width * ratio)
    canvas.value.height = Math.ceil(viewport.height * ratio)
    canvas.value.style.width = `${viewport.width}px`
    canvas.value.style.height = `${viewport.height}px`
    rendering = documentPage.render({ canvas: canvas.value, viewport,
      transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0] })
    await rendering.promise
  } catch (e) {
    if (!disposed && !(e instanceof Error && e.name === 'RenderingCancelledException')) {
      error.value = 'Не удалось показать страницу. Файл можно скачать.'
    }
  } finally { if (!disposed) busy.value = false }
}

onMounted(async () => {
  try {
    loading = getDocument({ url: props.url })
    pdf = await loading.promise
    if (disposed) return
    pages.value = pdf.numPages
    await renderPage()
  } catch {
    if (!disposed) { error.value = 'Не удалось открыть PDF. Если он защищён паролем, скачайте его.'; busy.value = false }
  }
})
watch(page, renderPage)
onBeforeUnmount(() => {
  disposed = true
  rendering?.cancel()
  void loading?.destroy()
})
</script>

<template>
  <div class="pdf-view" :aria-busy="busy">
    <div v-if="pages > 1" class="pdf-pages" aria-label="Страницы PDF">
      <button class="btn btn-sm" :disabled="busy || page === 1" @click="--page">Назад</button>
      <span class="small num">{{ page }} / {{ pages }}</span>
      <button class="btn btn-sm" :disabled="busy || page === pages" @click="++page">Вперёд</button>
    </div>
    <p v-if="busy" class="small muted" role="status">Открываем PDF…</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <div class="pdf-paper"><canvas ref="canvas" :aria-label="`${filename}, страница ${page}`" /></div>
  </div>
</template>

<style scoped>
.pdf-view { flex: 1; min-height: 0; overflow: auto; background: var(--bg); }
.pdf-pages { position: sticky; top: 0; display: flex; justify-content: center; align-items: center; gap: 12px; padding: 8px; background: var(--surface); z-index: 1; }
.pdf-paper { display: grid; justify-items: center; padding: 16px; }
canvas { max-width: 100%; background: white; }
.pdf-view > p { padding: 12px 16px 0; }
</style>
