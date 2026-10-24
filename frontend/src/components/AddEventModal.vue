<script setup lang="ts">
// Ожидаемое событие: «клиент обещал 300 000 ₽ 20-го». Попадает в прогноз сразу, источник — «вы добавили».
import { X } from 'lucide-vue-next'
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api, ApiError } from '../api'

const props = defineProps<{ companyId: string; minDate: string; presetTitle?: string; presetDirection?: 'in' | 'out' }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved'): void }>()

const dialog = ref<HTMLDialogElement | null>(null)
const direction = ref<'in' | 'out'>(props.presetDirection ?? 'in')
const amount = ref<number | null>(null)
const eventDate = ref('')
const title = ref(props.presetTitle ?? '')
const kind = ref('manual')
const confidence = ref('likely')
const error = ref('')
const busy = ref(false)
const idemKey = crypto.randomUUID()   // один ключ на открытие формы: двойной клик не создаст дубль

onMounted(() => dialog.value?.showModal())
onBeforeUnmount(() => dialog.value?.close())
const close = () => { if (!busy.value) emit('close') }

async function save() {
  if (busy.value) return
  error.value = ''
  busy.value = true
  try {
    await api.addEvent(props.companyId, {
      direction: direction.value, amount: String(amount.value), event_date: eventDate.value, title: title.value.trim(),
      kind: kind.value, confidence: confidence.value,
    }, idemKey)
    emit('saved')
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось сохранить'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <dialog ref="dialog" class="modal" aria-labelledby="event-title" @cancel.prevent="close">
    <form @submit.prevent="save">
      <div class="modal-body">
        <div class="modal-head">
          <div>
            <h2 id="event-title">Ожидаемый платёж</h2>
            <p class="small muted">Попадёт в прогноз сразу, с пометкой «вы добавили».</p>
          </div>
          <button type="button" class="btn btn-ghost btn-icon" aria-label="Закрыть" @click="close"><X /></button>
        </div>
        <fieldset :disabled="busy">
          <div class="seg dir" role="group" aria-label="Направление">
            <button type="button" :aria-pressed="direction === 'in'" @click="direction = 'in'">Деньги придут</button>
            <button type="button" :aria-pressed="direction === 'out'" @click="direction = 'out'">Деньги уйдут</button>
          </div>
          <div class="cols">
            <label class="field">Сумма, ₽ <input v-model.number="amount" type="number" inputmode="decimal" min="1" step="1" required /></label>
            <label class="field">Когда <input v-model="eventDate" type="date" :min="minDate" required /></label>
          </div>
          <label class="field">Что это
            <input v-model="title" maxlength="200" placeholder="Оплата от ООО «Ромашка» по счёту 512" required />
          </label>
          <div class="cols">
            <label class="field">Тип
              <select v-model="kind">
                <option value="invoice_out">Счёт клиенту</option>
                <option value="invoice_in">Счёт поставщика</option>
                <option value="contract">Платёж по договору</option>
                <option value="tax">Налог</option>
                <option value="manual">Другое</option>
              </select>
            </label>
            <label class="field">Насколько уверены
              <select v-model="confidence">
                <option value="certain">Точно</option>
                <option value="likely">Скорее всего</option>
                <option value="unsure">Не уверен</option>
              </select>
            </label>
          </div>
        </fieldset>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
      </div>
      <div class="modal-actions">
        <button type="button" class="btn" :disabled="busy" @click="close">Отмена</button>
        <button class="btn btn-primary" :disabled="busy">{{ busy ? 'Сохраняем…' : 'Добавить в прогноз' }}</button>
      </div>
    </form>
  </dialog>
</template>

<style scoped>
.dir { display: flex; width: 100%; margin-bottom: 16px; }
.dir button { flex: 1; }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 0 12px; }
@media (max-width: 480px) { .cols { grid-template-columns: 1fr; } }
</style>
