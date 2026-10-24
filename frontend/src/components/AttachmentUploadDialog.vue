<script setup lang="ts">
// Загрузка чека вместе с сопутствующими файлами (акт, договор, накладная) за один заход.
// Чек у операции один: новый заменяет прежний. Содержимое файлов ассистент не читает.
import { Lock, X } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, ApiError, type Attachment } from '../api'
import FilePicker from './FilePicker.vue'

const props = defineProps<{ operationId: string; hasReceipt: boolean; mode: 'receipt' | 'related' }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved', items: Attachment[]): void; (e: 'updated', items: Attachment[]): void }>()
const dialog = ref<HTMLDialogElement | null>(null)
const receipt = ref<File[]>([])
const related = ref<File[]>([])
const busy = ref(false)
const error = ref('')
const canSave = computed(() => receipt.value.length + related.value.length > 0)

onMounted(() => dialog.value?.showModal())
onBeforeUnmount(() => dialog.value?.close())
const close = () => { if (!busy.value) emit('close') }

async function save() {
  if (busy.value || !canSave.value) return
  busy.value = true
  error.value = ''
  let items: Attachment[] | null = null
  try {
    if (receipt.value.length) { items = await api.uploadAttachments(props.operationId, 'receipt', receipt.value); receipt.value = [] }
    if (related.value.length) { items = await api.uploadAttachments(props.operationId, 'related', related.value); related.value = [] }
    emit('saved', items ?? [])
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить файлы'
    if (items) {
      error.value = `Чек сохранён. Сопутствующие файлы не загрузились: ${error.value}`
      emit('updated', items) // Обновляем список, сохраняя диалог и выбранные файлы для повторной попытки.
    }
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <dialog ref="dialog" class="modal" aria-labelledby="att-title" @cancel.prevent="close">
    <form @submit.prevent="save">
      <div class="modal-body">
        <div class="modal-head">
          <div>
            <h2 id="att-title">{{ mode === 'receipt' ? (hasReceipt ? 'Заменить чек' : 'Прикрепить чек') : 'Добавить сопутствующие файлы' }}</h2>
            <p class="small muted">PDF, фото, документы Word и Excel, до 10 МБ каждый.</p>
          </div>
          <button type="button" class="btn btn-ghost btn-icon" aria-label="Закрыть" @click="close"><X /></button>
        </div>
        <fieldset :disabled="busy">
          <FilePicker v-if="mode === 'receipt'" v-model="receipt" label="Чек или платёжный документ"
                      :hint="hasReceipt ? 'Новый чек заменит прикреплённый' : 'Один файл'" />
          <FilePicker v-model="related" multiple label="Сопутствующие файлы" hint="Акт, договор, накладная, счёт. Необязательно" />
        </fieldset>
        <p class="privacy"><Lock aria-hidden="true" />Файлы видите только вы. Ассистент и модель прогноза их не читают.</p>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
      </div>
      <div class="modal-actions">
        <button type="button" class="btn" :disabled="busy" @click="close">Отмена</button>
        <button class="btn btn-primary" :disabled="busy || !canSave">{{ busy ? 'Загружаем…' : 'Загрузить' }}</button>
      </div>
    </form>
  </dialog>
</template>

<style scoped>
.privacy { display: flex; gap: 8px; align-items: flex-start; font-size: 13px; color: var(--ink-2); background: var(--bg); padding: 10px 12px; border-radius: var(--radius-s); }
.privacy svg { width: 16px; height: 16px; flex: none; margin-top: 2px; }
</style>
