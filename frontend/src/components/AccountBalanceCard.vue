<script setup lang="ts">
import { computed, inject, ref, watch, type Ref } from 'vue'
import { api, ApiError, type AccountBalance } from '../api'
import { BALANCE_SOURCE, humanDate, money } from '../format'

const props = defineProps<{ companyId: string }>()
const emit = defineEmits<{ (e: 'saved'): void }>()
const balance = inject<Ref<AccountBalance | null>>('balance')!
const reload = inject<() => Promise<void>>('reload')!
const toast = inject<(text: string) => void>('toast')!
const editing = ref(false)
const day = ref('')
const amount = ref('')
const busy = ref(false)
const error = ref('')
const today = new Intl.DateTimeFormat('sv-SE').format(new Date())
const maxDate = computed(() => balance.value?.first_operation_date ?? today)
const needsInitial = computed(() => balance.value?.source === 'unknown' || (balance.value?.unknown_operations ?? 0) > 0)
watch(balance, (value) => {
  if (!editing.value && value) {
    day.value = value.initial_date ?? value.first_operation_date ?? today
    amount.value = value.initial_amount ?? ''
  }
}, { immediate: true })

async function save() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await api.setInitialBalance(props.companyId, { date: day.value, amount: String(amount.value) })
    editing.value = false
    // В «Операциях» эта карточка исчезнет после reload, поэтому обновляем список до её размонтирования.
    emit('saved')
    await reload()
    toast('Начальный остаток сохранён. Остатки платежей пересчитаны')
  } catch (e) { error.value = e instanceof ApiError ? e.message : 'Не удалось сохранить остаток' }
  finally { busy.value = false }
}
</script>

<template>
  <section v-if="balance" class="card balance-card" aria-labelledby="account-balance-title">
    <h2 id="account-balance-title">Остаток на счёте</h2>
    <template v-if="balance.amount !== null">
      <p class="balance-amount num">{{ money(balance.amount) }}</p>
      <p class="small muted">{{ BALANCE_SOURCE[balance.source] }}<template v-if="balance.as_of"> · {{ humanDate(balance.as_of, true) }}</template></p>
      <p v-if="balance.source === 'calculated' && balance.anchor_date" class="small muted">
        Опора: {{ balance.anchor_source === 'statement' ? 'выписка' : balance.anchor_source === 'legacy' ? 'ранее введённый остаток' : 'начальный остаток' }} от {{ humanDate(balance.anchor_date, true) }}.
      </p>
    </template>
    <p v-else class="small muted">Остаток пока неизвестен. Укажите начальную сумму один раз или загрузите выписку. Проведённые платежи можно добавлять уже сейчас.</p>
    <p v-if="balance.unknown_operations" class="small warn">Операций с неизвестным остатком: {{ balance.unknown_operations }}. Для их учёта в прогнозе задайте сумму на начало первого дня истории.</p>
    <p v-if="balance.initial_date" class="small muted">Начальный остаток: {{ money(balance.initial_amount!) }} на начало {{ humanDate(balance.initial_date, true) }}.</p>
    <form v-if="needsInitial || editing" class="initial-form" @submit.prevent="save">
      <p class="small">Сумма на начало дня, до всех платежей этой даты. Поступления прибавляются, списания вычитаются. Остатки из выписки имеют приоритет.</p>
      <fieldset :disabled="busy" class="fields">
        <label class="field">Начальный остаток, ₽
          <input v-model="amount" type="number" inputmode="decimal" min="-99999999999999.99" max="99999999999999.99" step="0.01" required />
        </label>
        <label class="field">Дата начального остатка
          <input v-model="day" type="date" :max="maxDate" required />
        </label>
      </fieldset>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <div class="actions">
        <button class="btn btn-primary" :disabled="busy">{{ busy ? 'Сохраняем…' : 'Сохранить начальный остаток' }}</button>
        <button v-if="editing && !needsInitial" type="button" class="btn" :disabled="busy" @click="editing = false">Отмена</button>
      </div>
    </form>
    <button v-else-if="balance.initial_date" class="btn btn-sm" @click="day = balance.initial_date; amount = balance.initial_amount ?? ''; editing = true">Изменить начальный остаток</button>
  </section>
</template>

<style scoped>
.balance-card { display: grid; gap: 12px; align-content: start; }
.balance-amount { font-size: 24px; font-weight: 650; }
.initial-form { display: grid; gap: 12px; width: 100%; }
.fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.field { margin-bottom: 0; }
.actions { display: flex; gap: 8px; flex-wrap: wrap; }
@media (max-width: 600px) { .fields { grid-template-columns: 1fr; } }
</style>
