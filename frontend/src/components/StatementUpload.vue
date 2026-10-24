<script setup lang="ts">
// Загрузка выписки. Два вида: крупная зона «Нужна одна загрузка» (первый вход) и компактная кнопка.
import { FileUp, LoaderCircle } from 'lucide-vue-next'
import { ref } from 'vue'
import { api, ApiError, type ImportResult } from '../api'

const props = withDefaults(defineProps<{ companyId?: string; variant?: 'zone' | 'button'; label?: string }>(),
  { variant: 'button', label: 'Загрузить выписку' })
const emit = defineEmits<{ (e: 'imported', results: ImportResult[]): void; (e: 'error', message: string): void }>()
const busy = ref(false)
const error = ref('')
const over = ref(false)
const id = `st-${Math.random().toString(36).slice(2, 9)}`

async function send(file: File | undefined) {
  if (!file || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const results = props.companyId ? await api.uploadStatement(props.companyId, file) : await api.importStatement(file)
    emit('imported', results)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить выписку'
    emit('error', error.value)
  } finally { busy.value = false }
}
function onInput(ev: Event) {
  const input = ev.target as HTMLInputElement
  send(input.files?.[0]).finally(() => { input.value = '' })
}
function onDrop(ev: DragEvent) { over.value = false; send(ev.dataTransfer?.files?.[0]) }
</script>

<template>
  <div v-if="variant === 'zone'" class="zone" :class="{ over, busy }" @dragover.prevent="over = true"
       @dragleave="over = false" @drop.prevent="onDrop">
    <FileUp v-if="!busy" class="z-ico" aria-hidden="true" />
    <LoaderCircle v-else class="z-ico spin" aria-hidden="true" />
    <p class="z-title">{{ busy ? 'Разбираем выписку…' : 'Перетащите файл выписки сюда' }}</p>
    <p class="small muted">CSV, TXT в формате 1С (1CClientBankExchange) или текстовый PDF Райффайзенбанка</p>
    <label class="btn btn-primary" :for="id">Выбрать файл</label>
    <input :id="id" class="visually-hidden" type="file" accept=".csv,.txt,.pdf" :disabled="busy" @change="onInput" />
    <p v-if="error" class="error" role="alert">{{ error }}</p>
  </div>
  <span v-else class="inline">
    <label class="btn" :class="{ busy }" :for="id"><FileUp />{{ busy ? 'Загружаем…' : label }}</label>
    <input :id="id" class="visually-hidden" type="file" accept=".csv,.txt,.pdf" :disabled="busy" @change="onInput" />
  </span>
</template>

<style scoped>
.zone {
  display: grid; justify-items: center; text-align: center; gap: 8px; padding: 40px 24px;
  border: 2px dashed var(--line-strong); border-radius: 14px; background: var(--surface); transition: border-color 150ms, background 150ms;
}
.zone.over { border-color: var(--brand); background: var(--brand-soft); }
.zone .btn { margin-top: 8px; cursor: pointer; }
.z-ico { width: 36px; height: 36px; color: var(--brand); }
.z-title { font-size: 18px; font-weight: 600; }
.zone:focus-within .btn, .inline:focus-within .btn { outline: 3px solid color-mix(in srgb, var(--brand) 45%, transparent); outline-offset: 2px; }
.inline label { cursor: pointer; }
.busy { opacity: 0.7; cursor: progress; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
