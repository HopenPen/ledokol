<script setup lang="ts">
// Документы операций не передаются автоматически; пользователь отдельно выбирает файлы для чата.
import { Paperclip, Send, X } from 'lucide-vue-next'
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, ApiError } from '../api'

const props = defineProps<{ companyId: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()
const question = ref('')
type Message = { q: string; a: string; by: string; files?: string[] }
const selectedFiles = ref<File[]>([])
const fileInput = ref<HTMLInputElement | null>(null)
const fileError = ref('')
const fileConsent = ref(false)
function chooseFiles(event: Event) {
  const element = event.target as HTMLInputElement
  const files = [...selectedFiles.value, ...Array.from(element.files ?? [])]
  element.value = ''
  fileError.value = ''
  if (files.length > 3 || files.some(file => file.size > 5 * 1024 * 1024) || files.reduce((sum, f) => sum + f.size, 0) > 10 * 1024 * 1024) {
    fileError.value = 'До 3 файлов, каждый до 5 МБ, вместе до 10 МБ'
    return
  }
  selectedFiles.value = files
  fileConsent.value = false
}
const storageKey = `cashflow.chat.${props.companyId}`
function savedHistory(): Message[] {
  try {
    const saved: unknown = JSON.parse(sessionStorage.getItem(storageKey) ?? '[]')
    if (!Array.isArray(saved)) return []
    return saved.filter((m): m is Message => m && typeof m.q === 'string' && typeof m.a === 'string' && typeof m.by === 'string')
      .slice(-50).map(m => m.a ? m : { ...m, a: 'Ответ был прерван. Отправьте вопрос ещё раз.', by: 'error' })
  } catch { return [] }
}
const history = ref<Message[]>(savedHistory())
function persistHistory() {
  try { sessionStorage.setItem(storageKey, JSON.stringify(history.value.slice(-50))) } catch { /* storage may be unavailable */ }
}
watch(history, persistHistory, { deep: true, flush: 'sync' })
const busy = ref(false)
const log = ref<HTMLDivElement | null>(null)
const input = ref<HTMLInputElement | null>(null)
const CHIPS = ['Хватит ли денег до зарплаты?', 'Почему может не хватить денег?', 'Что будет, если клиент заплатит позже?']

async function send(q = question.value) {
  if ((!q.trim() && !selectedFiles.value.length) || busy.value || (selectedFiles.value.length && !fileConsent.value)) return
  const files = [...selectedFiles.value]
  const text = q.trim() || 'Разбери прикреплённые файлы'
  busy.value = true
  const index = history.value.length
  history.value.push({ q: text, a: '', by: '', files: files.map(file => file.name) })
  question.value = ''
  selectedFiles.value = []
  fileConsent.value = false
  await nextTick()
  log.value?.scrollTo({ top: log.value.scrollHeight })
  try {
    const r = files.length ? await api.askWithFiles(props.companyId, text, files) : await api.ask(props.companyId, text)
    Object.assign(history.value[index], { a: r.answer, by: r.generated_by })
  } catch (e) {
    Object.assign(history.value[index], { a: e instanceof ApiError ? e.message : 'Не получилось ответить', by: 'error' })
  } finally {
    persistHistory()
    busy.value = false
    await nextTick()
    log.value?.scrollTo({ top: log.value.scrollHeight })
  }
}
const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') emit('close') }
onMounted(() => { window.addEventListener('keydown', onKey); input.value?.focus() })
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <aside class="panel" role="dialog" aria-modal="false" aria-labelledby="ask-title">
    <header>
      <div><h2 id="ask-title">Спросить о своих деньгах</h2><p class="tiny">Ответ строится по вашему прогнозу</p></div>
      <button class="btn btn-ghost btn-icon" aria-label="Закрыть" @click="emit('close')"><X /></button>
    </header>
    <div ref="log" class="log">
      <div v-if="!history.length" class="chips">
        <button v-for="c in CHIPS" :key="c" class="btn btn-sm chip-btn" @click="send(c)">{{ c }}</button>
      </div>
      <div v-for="(m, i) in history" :key="i" class="msg">
        <p class="q">{{ m.q }}</p>
        <p v-for="name in m.files" :key="name" class="tiny file-name">{{ name }}</p>
        <p v-if="m.a" class="a" :class="{ err: m.by === 'error' }">{{ m.a }}</p>
        <p v-if="m.a && m.by !== 'error'" class="tiny">{{ m.by === 'template' ? 'Ответ по шаблону, цифры из прогноза' : 'Ответ сгенерирован моделью, цифры из прогноза' }}</p>
      </div>
      <p v-if="busy" class="tiny">Думаем…</p>
    </div>
    <div v-if="selectedFiles.length" class="attachments">
      <div v-for="(file, index) in selectedFiles" :key="index" class="file-row">
        <span>{{ file.name }}</span><button class="btn btn-ghost btn-icon" :aria-label="`Убрать ${file.name}`" @click="selectedFiles.splice(index, 1)"><X /></button>
      </div>
      <label class="tiny consent"><input v-model="fileConsent" type="checkbox" />Передать выбранные файлы RouterAI для анализа</label>
    </div>
    <p v-if="fileError" class="tiny err" role="alert">{{ fileError }}</p>
    <form @submit.prevent="send()">
      <input ref="fileInput" type="file" hidden multiple accept=".pdf,.txt,.csv,.md,.png,.jpg,.jpeg,.webp" @change="chooseFiles" />
      <button type="button" class="btn btn-ghost btn-icon" :disabled="busy" aria-label="Прикрепить файлы" title="PDF, текст или изображение" @click="fileInput?.click()"><Paperclip /></button>
      <input ref="input" v-model="question" class="input" maxlength="500" placeholder="Например: хватит ли денег до 20 ноября?" aria-label="Вопрос" />
      <button class="btn btn-primary btn-icon" :disabled="busy || (!question.trim() && !selectedFiles.length) || (selectedFiles.length > 0 && !fileConsent)" aria-label="Отправить"><Send /></button>
    </form>
    <p class="tiny privacy">Ассистент получает обезличенный прогноз. Выбранные здесь файлы передаются RouterAI после вашего подтверждения; документы операций автоматически не передаются.</p>
  </aside>
</template>

<style scoped>
.panel {
  position: fixed; right: 16px; bottom: 16px; top: 80px; width: min(420px, calc(100% - 32px)); z-index: 40;
  display: flex; flex-direction: column; gap: 12px; padding: 20px; background: var(--surface);
  border: 1px solid var(--line); border-radius: 14px; box-shadow: var(--shadow-pop);
}
header { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
h2 { font-size: 18px; }
.log { flex: 1; overflow-y: auto; display: grid; gap: 16px; align-content: start; }
.chips { display: grid; gap: 6px; justify-items: start; }
.chip-btn { white-space: normal; text-align: left; }
.msg { display: grid; gap: 4px; }
.q { justify-self: end; background: var(--brand-soft); color: var(--ink); padding: 8px 12px; border-radius: 12px 12px 4px 12px; max-width: 85%; }
.a { background: var(--bg); padding: 10px 12px; border-radius: 12px 12px 12px 4px; }
.a.err { color: var(--risk); }
.attachments { display: grid; gap: 4px; }
.file-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 13px; }
.file-row span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-name { text-align: right; overflow-wrap: anywhere; }
.consent { display: flex; align-items: flex-start; gap: 8px; }
.err { color: var(--risk); }
form { display: flex; gap: 8px; }
form .input { min-height: 40px; }
.privacy { border-top: 1px solid var(--line); padding-top: 8px; }
@media (max-width: 640px) { .panel { top: 16px; } }
</style>
