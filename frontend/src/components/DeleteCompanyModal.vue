<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api, ApiError, type Company } from '../api'

const props = defineProps<{ company: Company }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'deleted', id: string): void }>()
const dialog = ref<HTMLDialogElement | null>(null)
const busy = ref(false)
const error = ref('')

onMounted(() => dialog.value?.showModal())
onBeforeUnmount(() => dialog.value?.close())
const close = () => { if (!busy.value) emit('close') }

async function remove() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await api.deleteCompany(props.company.id)
    emit('deleted', props.company.id)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось удалить компанию. Попробуйте ещё раз.'
  } finally { busy.value = false }
}
</script>

<template>
  <dialog ref="dialog" class="modal" aria-labelledby="delete-company-title" aria-describedby="delete-company-description" @cancel.prevent="close">
    <form @submit.prevent="remove">
      <div class="modal-body">
        <h2 id="delete-company-title">Удалить компанию?</h2>
        <p class="company-name">{{ company.name }}</p>
        <p id="delete-company-description">Будут безвозвратно удалены все её платежи, документы, ожидаемые платежи, история выписок, остатки и прогнозы. Действие нельзя отменить.</p>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
      </div>
      <div class="modal-actions">
        <button type="button" class="btn" :disabled="busy" autofocus @click="close">Отмена</button>
        <button class="btn btn-danger" :disabled="busy">{{ busy ? 'Удаляем…' : 'Удалить компанию' }}</button>
      </div>
    </form>
  </dialog>
</template>

<style scoped>
.modal-body { display: grid; gap: 12px; }
.company-name { font-weight: 600; overflow-wrap: anywhere; }
</style>
