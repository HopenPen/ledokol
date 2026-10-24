<script setup lang="ts">
// Поле выбора файлов с понятным списком выбранного. Проверяем формат и размер ещё до отправки,
// окончательная проверка всё равно на сервере.
import { FileUp, X } from 'lucide-vue-next'
import { ref } from 'vue'
import { ATTACH_ACCEPT, ATTACH_EXT, ATTACH_MAX_MB } from '../files'
import { fileSize } from '../format'

const props = withDefaults(defineProps<{ label: string; hint?: string; multiple?: boolean; maxFiles?: number; maxMb?: number }>(),
  { hint: '', multiple: false, maxFiles: 10, maxMb: ATTACH_MAX_MB })
const files = defineModel<File[]>({ default: () => [] })
const error = ref('')
const input = ref<HTMLInputElement | null>(null)
const id = `fp-${Math.random().toString(36).slice(2, 9)}`

function onPick(ev: Event) {
  error.value = ''
  const picked = Array.from((ev.target as HTMLInputElement).files ?? [])
  const bad = picked.find((f) => !ATTACH_EXT.has(f.name.split('.').pop()?.toLowerCase() ?? ''))
  const big = picked.find((f) => f.size > props.maxMb * 1024 * 1024)
  if (bad) error.value = `«${bad.name}»: такой формат не подойдёт`
  else if (big) error.value = `«${big.name}» больше ${props.maxMb} МБ`
  else {
    const next = props.multiple ? [...files.value, ...picked] : picked.slice(0, 1)
    if (next.length > props.maxFiles) error.value = `Не больше ${props.maxFiles} файлов за раз`
    else files.value = next
  }
  if (input.value) input.value.value = ''
}
const remove = (i: number) => { files.value = files.value.filter((_, j) => j !== i) }
</script>

<template>
  <div class="picker">
    <p class="p-label" :id="`${id}-l`">{{ label }}</p>
    <p v-if="hint" class="tiny">{{ hint }}</p>
    <ul v-if="files.length" class="chosen">
      <li v-for="(f, i) in files" :key="f.name + i">
        <span class="name">{{ f.name }}</span><span class="tiny">{{ fileSize(f.size) }}</span>
        <button type="button" class="btn btn-ghost btn-icon" :aria-label="`Убрать ${f.name}`" @click="remove(i)"><X /></button>
      </li>
    </ul>
    <label v-if="multiple || !files.length" class="btn btn-sm drop" :for="id">
      <FileUp />{{ multiple && files.length ? 'Добавить ещё' : 'Выбрать файл' }}
    </label>
    <input :id="id" ref="input" class="visually-hidden" type="file" :accept="ATTACH_ACCEPT" :multiple="multiple"
           :aria-labelledby="`${id}-l`" @change="onPick" />
    <p v-if="error" class="error" role="alert">{{ error }}</p>
  </div>
</template>

<style scoped>
.picker { display: grid; gap: 6px; justify-items: start; margin-bottom: 16px; }
.p-label { font-size: 14px; font-weight: 550; }
.chosen { list-style: none; padding: 0; margin: 0; width: 100%; display: grid; gap: 4px; }
.chosen li { display: flex; align-items: center; gap: 8px; padding: 4px 4px 4px 12px; background: var(--bg); border-radius: var(--radius-s); }
.name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }
.drop { cursor: pointer; }
input:focus-visible + .drop, .picker:focus-within .drop { outline: 3px solid var(--brand-soft); }
</style>
