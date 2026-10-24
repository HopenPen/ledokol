<script setup lang="ts">
import { ref } from 'vue'
import { api, type ImportResult } from '../api'

const props = defineProps<{ companyId?: string }>()
const emit = defineEmits<{ (e: 'imported', results: ImportResult[]): void }>()
const busy = ref(false)
const error = ref('')
const message = ref('')
const warnings = ref<string[]>([])
async function upload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || busy.value) return
  busy.value = true
  error.value = message.value = ''
  warnings.value = []
  try {
    const results = props.companyId ? await api.uploadStatement(props.companyId, file) : await api.importStatement(file)
    message.value = results.every((r) => r.already_imported) ? 'Этот файл уже загружен' : `Добавлено платежей: ${results.reduce((n, r) => n + r.rows_new, 0)}`
    warnings.value = [...new Set(results.flatMap((r) => r.quality.warnings))]
    emit('imported', results)
  } catch (e) { error.value = e instanceof Error ? e.message : 'Не удалось загрузить выписку' }
  finally { busy.value = false; input.value = '' }
}
</script>

<template>
  <div>
    <label class="btn upload" :class="{ busy }">
      {{ busy ? 'Загружаем…' : 'Загрузить выписку' }}
      <input type="file" accept=".csv,.txt,.pdf" :disabled="busy" @change="upload" />
    </label>
    <p class="hint">CSV · TXT 1С-клиент-банк · текстовый PDF Райффайзенбанка</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="message" role="status">{{ message }}</p>
    <p v-for="warning in warnings" :key="warning" class="hint">{{ warning }}</p>
  </div>
</template>

<style scoped>
.upload { display: inline-block; position: relative; }
input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.upload:focus-within { outline: 2px solid var(--green); outline-offset: 2px; }
.busy { opacity: 0.6; cursor: wait; }
.hint { color: var(--muted); font-size: 13px; margin: 8px 0; }
</style>
