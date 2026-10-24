<script setup lang="ts">
import { ref } from 'vue'
import { api, ApiError } from '../api'

const props = defineProps<{ companyId: string; minDate: string; presetTitle?: string }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved'): void }>()

const direction = ref<'in' | 'out'>('in')
const amount = ref<number | null>(null)
const eventDate = ref('')
const title = ref(props.presetTitle ?? '')
const kind = ref('manual')
const confidence = ref('likely')
const error = ref('')
const busy = ref(false)
const idemKey = crypto.randomUUID()   // один ключ на открытие формы — повторный клик не создаст дубль

async function save() {
  error.value = ''
  busy.value = true
  try {
    await api.addEvent(props.companyId, {
      direction: direction.value, amount: String(amount.value), event_date: eventDate.value, title: title.value,
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
  <div class="backdrop" @click.self="emit('close')">
    <form class="card modal" role="dialog" aria-label="Добавить событие" @submit.prevent="save">
      <h2>Добавить событие</h2>
      <div class="seg" role="radiogroup">
        <button type="button" class="btn" :class="{ on: direction === 'in' }" @click="direction = 'in'">Деньги придут</button>
        <button type="button" class="btn" :class="{ on: direction === 'out' }" @click="direction = 'out'">Деньги уйдут</button>
      </div>
      <label class="field">Сумма, ₽ <input v-model.number="amount" type="number" min="1" step="1" required /></label>
      <label class="field">Когда <input v-model="eventDate" type="date" :min="minDate" required /></label>
      <label class="field">Что это <input v-model="title" maxlength="200" placeholder="Оплата от ООО Ромашка" required /></label>
      <label class="field">Тип
        <select v-model="kind">
          <option value="invoice_out">Счёт клиенту</option>
          <option value="invoice_in">Счёт поставщика</option>
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
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <div class="row">
        <button type="button" class="btn" @click="emit('close')">Отмена</button>
        <button class="btn btn-primary" :disabled="busy">Добавить в прогноз</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.backdrop { position: fixed; inset: 0; background: rgb(19 36 29 / 0.35); display: grid; place-items: center; padding: 16px; z-index: 10; }
.modal { width: min(440px, 100%); }
h2 { font-size: 20px; margin-bottom: 12px; }
.seg { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px; }
.seg .on { border-color: var(--green); background: var(--green-wash); color: var(--green); }
.row { display: flex; justify-content: flex-end; gap: 8px; }
</style>
