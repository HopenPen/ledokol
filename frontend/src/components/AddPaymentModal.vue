<script setup lang="ts">
// Проведённый платёж вручную + чек и сопутствующие файлы в том же окне.
// Сначала сохраняем платёж (с ключом идемпотентности), потом файлы. Если файлы не загрузились,
// платёж уже есть: говорим об этом прямо и предлагаем дозагрузить из карточки операции.
import { X } from 'lucide-vue-next'
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api, ApiError } from '../api'
import FilePicker from './FilePicker.vue'

const props = defineProps<{ companyId: string }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved', warning: string): void }>()
const dialog = ref<HTMLDialogElement | null>(null)
const today = new Intl.DateTimeFormat('sv-SE').format(new Date())
const opDate = ref(today)
const direction = ref<'in' | 'out'>('out')
const amount = ref('')
const name = ref('')
const inn = ref('')
const purpose = ref('')
const balance = ref('')
const receipt = ref<File[]>([])
const related = ref<File[]>([])
const busy = ref(false)
const error = ref('')
const key = crypto.randomUUID()
onMounted(() => dialog.value?.showModal())
onBeforeUnmount(() => dialog.value?.close())
const close = () => { if (!busy.value) emit('close') }

async function save() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const op = await api.addPayment(props.companyId, {
      op_date: opDate.value, amount: String(amount.value), direction: direction.value,
      counterparty_name: name.value.trim(), counterparty_inn: inn.value.trim(), purpose: purpose.value.trim(),
      balance_eod: String(balance.value),
    }, key)
    let warning = ''
    try {
      if (receipt.value.length) await api.uploadAttachments(op.id, 'receipt', receipt.value)
      if (related.value.length) await api.uploadAttachments(op.id, 'related', related.value)
    } catch (e) {
      warning = `Платёж сохранён, но файлы не загрузились: ${e instanceof ApiError ? e.message : 'ошибка сети'}. Прикрепите их в карточке операции.`
    }
    emit('saved', warning)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось сохранить платёж'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <dialog ref="dialog" class="modal" aria-labelledby="payment-title" @cancel.prevent="close">
    <form @submit.prevent="save">
      <div class="modal-body">
        <div class="modal-head">
          <div>
            <h2 id="payment-title">Добавить платёж</h2>
            <p class="small muted">Операция, которая уже прошла по счёту, с чеком и документами.</p>
          </div>
          <button type="button" class="btn btn-ghost btn-icon" aria-label="Закрыть" @click="close"><X /></button>
        </div>
        <fieldset :disabled="busy">
          <div class="seg dir" role="group" aria-label="Направление">
            <button type="button" :aria-pressed="direction === 'out'" @click="direction = 'out'">Списание</button>
            <button type="button" :aria-pressed="direction === 'in'" @click="direction = 'in'">Поступление</button>
          </div>
          <div class="cols">
            <label class="field">Сумма, ₽ <input v-model="amount" type="number" inputmode="decimal" min="0.01" max="99999999999999.99" step="0.01" required /></label>
            <label class="field">Дата <input v-model="opDate" type="date" :max="today" required /></label>
          </div>
          <label class="field">Контрагент <input v-model="name" maxlength="300" required /></label>
          <label class="field">ИНН контрагента <span class="hint">Необязательно, 10 или 12 цифр</span>
            <input v-model="inn" inputmode="numeric" pattern="(?:\d{10}|\d{12})?" maxlength="12" />
          </label>
          <label class="field">Назначение платежа <input v-model="purpose" maxlength="2000" required /></label>
          <label class="field">Остаток на счёте в конце этого дня, ₽
            <input v-model="balance" type="number" inputmode="decimal" min="-99999999999999.99" max="99999999999999.99" step="0.01" required />
            <span class="hint">Применяется ко всем операциям этого дня</span>
          </label>
          <div class="files">
            <FilePicker v-model="receipt" label="Чек" hint="Чек или платёжное поручение, один файл. Необязательно" />
            <FilePicker v-model="related" multiple label="Сопутствующие файлы" hint="Акт, договор, накладная. Необязательно" />
            <p class="tiny">Файлы видите только вы. Ассистент и модель прогноза их не читают.</p>
          </div>
        </fieldset>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
      </div>
      <div class="modal-actions">
        <button type="button" class="btn" :disabled="busy" @click="close">Отмена</button>
        <button class="btn btn-primary" :disabled="busy">{{ busy ? 'Сохраняем…' : 'Сохранить платёж' }}</button>
      </div>
    </form>
  </dialog>
</template>

<style scoped>
.dir { display: flex; width: 100%; margin-bottom: 16px; }
.dir button { flex: 1; }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 0 12px; }
.files { border-top: 1px solid var(--line); padding-top: 16px; }
@media (max-width: 480px) { .cols { grid-template-columns: 1fr; } }
</style>
