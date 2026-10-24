<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'

const props = defineProps<{ companyId: string }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved'): void }>()
const dialog = ref<HTMLDialogElement | null>(null)
const today = new Intl.DateTimeFormat('sv-SE').format(new Date())
const opDate = ref(today)
const direction = ref<'in' | 'out'>('in')
const amount = ref('')
const name = ref('')
const inn = ref('')
const purpose = ref('')
const balance = ref('')
const busy = ref(false)
const error = ref('')
const key = crypto.randomUUID()
onMounted(() => dialog.value?.showModal())
onBeforeUnmount(() => dialog.value?.close())
function close() { if (!busy.value) emit('close') }

async function save() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await api.addPayment(props.companyId, {
      op_date: opDate.value, amount: String(amount.value), direction: direction.value,
      counterparty_name: name.value, counterparty_inn: inn.value, purpose: purpose.value, balance_eod: String(balance.value),
    }, key)
    emit('saved')
  } catch (e) { error.value = e instanceof Error ? e.message : 'Не удалось сохранить платёж' }
  finally { busy.value = false }
}
</script>

<template>
  <dialog ref="dialog" class="card modal" aria-labelledby="payment-title" @cancel.prevent="close">
    <form @submit.prevent="save">
      <h2 id="payment-title">Добавить платёж</h2>
      <p class="hint">Проведённая операция по счёту</p>
      <fieldset :disabled="busy">
        <div class="columns">
          <label class="field">Направление
            <select v-model="direction"><option value="in">Поступление</option><option value="out">Списание</option></select>
          </label>
          <label class="field">Дата <input v-model="opDate" type="date" :max="today" required /></label>
        </div>
        <label class="field">Сумма, ₽ <input v-model="amount" type="number" min="0.01" max="99999999999999.99" step="0.01" required /></label>
        <label class="field">Контрагент <input v-model="name" maxlength="300" required /></label>
        <label class="field">ИНН контрагента <input v-model="inn" inputmode="numeric" pattern="(?:\d{10}|\d{12})?" maxlength="12" placeholder="Необязательно" /></label>
        <label class="field">Назначение платежа <input v-model="purpose" maxlength="2000" required /></label>
        <label class="field">Остаток на конец дня, ₽ <input v-model="balance" type="number" min="-99999999999999.99" max="99999999999999.99" step="0.01" required /></label>
        <p class="hint">Укажите итоговый остаток по счёту за выбранную дату. Он применяется ко всем операциям этого дня.</p>
      </fieldset>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <div class="actions">
        <button type="button" class="btn" :disabled="busy" @click="close">Отмена</button>
        <button class="btn btn-primary" :disabled="busy">{{ busy ? 'Сохраняем…' : 'Сохранить платёж' }}</button>
      </div>
    </form>
  </dialog>
</template>

<style scoped>
.modal { width: min(480px, calc(100% - 32px)); max-height: calc(100vh - 32px); color: var(--ink); }
.modal::backdrop { background: rgb(19 36 29 / 0.35); }
fieldset { border: 0; margin: 0; padding: 0; }
.columns { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.hint { color: var(--ink-2); font-size: 13px; margin: 8px 0 16px; }
.actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
