<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, ApiError, type EventInput, type Forecast } from '../api'
import { humanDate, rub } from '../format'
import BalanceChart from './BalanceChart.vue'

const props = defineProps<{
  companyId: string; base: Forecast; history: { date: string; balance: number }[]; presetTitle?: string
}>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved'): void }>()
const dialog = ref<HTMLDialogElement>()
const summary = ref<HTMLElement>()
const amountInput = ref<HTMLInputElement>()
const direction = ref<EventInput['direction']>('in')
const amount = ref<number | null>(null)
const eventDate = ref('')
const title = ref(props.presetTitle ?? '')
const kind = ref<EventInput['kind']>('manual')
const confidence = ref<EventInput['confidence']>('likely')
const error = ref('')
const calculating = ref(false)
const saving = ref(false)
const result = ref<Forecast | null>(null)
const busy = computed(() => calculating.value || saving.value)
const payload = computed<EventInput>(() => ({
  direction: direction.value, amount: String(amount.value ?? ''), event_date: eventDate.value,
  title: title.value.trim(), kind: kind.value, confidence: confidence.value,
}))
const fingerprint = computed(() => JSON.stringify(payload.value))
const idemKey = crypto.randomUUID() // один ключ на форму, в том числе после сетевой ошибки
let checkedFingerprint = ''
let revision = 0
let disposed = false
let previousOverflow = ''

watch([fingerprint, () => props.base], () => {
  revision += 1
  result.value = null
  checkedFingerprint = ''
  error.value = ''
})

const change = computed(() => {
  if (!result.value) return 0
  return result.value.points.at(-1)!.p50 - props.base.points.at(-1)!.p50
})
const firstDay = computed(() => props.base.points[0]?.date ?? props.base.as_of)
const lastDay = computed(() => props.base.points.at(-1)?.date ?? props.base.as_of)
const beyondHorizon = computed(() => eventDate.value > lastDay.value)

async function preview() {
  if (busy.value) return
  error.value = ''
  if (!beyondHorizon.value && !props.base.points.some((p) => p.date === eventDate.value)) {
    error.value = 'Выберите рабочий день в указанном периоде — на выходные прогноз не рассчитывается.'
    return
  }
  if (!title.value.trim()) {
    error.value = 'Добавьте название события, чтобы найти его в прогнозе.'
    return
  }
  calculating.value = true
  const currentRevision = revision
  const submittedFingerprint = fingerprint.value
  try {
    const forecast = await api.preview(props.companyId, { extra_events: [payload.value], horizon: props.base.points.length })
    if (disposed || currentRevision !== revision) return
    result.value = forecast
    checkedFingerprint = submittedFingerprint
    await nextTick()
    summary.value?.focus()
  } catch (e) {
    if (!disposed && currentRevision === revision) {
      error.value = e instanceof ApiError ? e.message : 'Не удалось проверить прогноз. Повторите расчёт.'
    }
  } finally {
    calculating.value = false
  }
}

async function save() {
  if (busy.value || !result.value || checkedFingerprint !== fingerprint.value) return
  saving.value = true
  error.value = ''
  try {
    await api.addEvent(props.companyId, payload.value, idemKey)
    emit('saved')
  } catch (e) {
    error.value = e instanceof ApiError ? e.message
      : 'Не удалось подтвердить сохранение. Повторите — второе событие не появится.'
  } finally {
    saving.value = false
  }
}

function close() {
  if (saving.value) return
  dialog.value?.close()
  emit('close')
}

onMounted(() => {
  previousOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  dialog.value?.showModal()
  amountInput.value?.focus()
})
onBeforeUnmount(() => {
  disposed = true
  dialog.value?.close()
  document.body.style.overflow = previousOverflow
})
</script>

<template>
  <dialog ref="dialog" class="draft" aria-labelledby="draft-title" aria-describedby="draft-description"
          @cancel.prevent="close" @click.self="close">
    <div class="draft-content">
      <header class="draft-head">
        <div>
          <h2 id="draft-title">Добавить событие</h2>
          <p id="draft-description">Сначала проверьте, как изменится прогноз. Событие появится в нём после сохранения.</p>
        </div>
        <button type="button" class="btn close" :disabled="saving" aria-label="Закрыть черновик" @click="close">Закрыть</button>
      </header>

      <div class="draft-layout">
        <form class="event-form" @submit.prevent="result ? save() : preview()">
          <fieldset :disabled="busy">
            <legend class="visually-hidden">Ожидаемое событие</legend>
            <div class="direction" role="group" aria-label="Направление платежа">
              <button type="button" class="btn" :class="{ on: direction === 'in' }" :aria-pressed="direction === 'in'"
                      @click="direction = 'in'">Деньги придут</button>
              <button type="button" class="btn" :class="{ on: direction === 'out' }" :aria-pressed="direction === 'out'"
                      @click="direction = 'out'">Деньги уйдут</button>
            </div>
            <label class="field">Сумма, ₽
              <input ref="amountInput" v-model.number="amount" type="number" min="0.01" max="99999999999999.99"
                     step="0.01" inputmode="decimal" required />
            </label>
            <label class="field">Когда
              <input v-model="eventDate" type="date" :min="firstDay" aria-describedby="draft-period" required />
            </label>
            <p id="draft-period" class="hint">Проверка на {{ base.points.length }} рабочих дней: с {{ humanDate(firstDay) }} по {{ humanDate(lastDay) }}.</p>
            <p v-if="beyondHorizon" class="hint">Событие позже этого периода. Оно сохранится, но пока не изменит линии на графике.</p>
            <label class="field">Что это
              <input v-model="title" maxlength="200" placeholder="Например, оплата от клиента" required />
            </label>
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
                <option value="certain">Точно — 100%</option>
                <option value="likely">Скорее всего — 80%</option>
                <option value="unsure">Не уверен — 50%</option>
              </select>
            </label>
          </fieldset>
          <p v-if="error" class="error" role="alert">{{ error }}</p>
          <div class="actions">
            <button type="button" class="btn" :disabled="saving" @click="close">Отменить</button>
            <button class="btn btn-primary" :disabled="busy">
              {{ saving ? 'Сохраняем…' : calculating ? 'Проверяем…' : result ? 'Сохранить событие' : 'Проверить прогноз' }}
            </button>
          </div>
          <p class="hint save-note">{{ result ? 'Можно изменить поля и проверить ещё раз.' : 'До сохранения данные остаются прежними.' }}</p>
        </form>

        <section class="preview" aria-label="Предпросмотр прогноза" :aria-busy="calculating">
          <div v-if="!result" class="preview-empty" role="status">
            <h3>{{ calculating ? 'Проверяем влияние события…' : 'Как событие повлияет на деньги' }}</h3>
            <p>{{ calculating ? 'Считаем прогноз с выбранной суммой, датой и уверенностью.' : 'Заполните поля и нажмите «Проверить прогноз». Здесь сравним текущий прогноз и прогноз с новым событием.' }}</p>
          </div>
          <template v-else>
            <div ref="summary" class="preview-summary" tabindex="-1" role="status">
              <h3>{{ result.headline }}</h3>
              <p v-if="Math.abs(change) < 0.01">На конец периода остаток не изменится.</p>
              <p v-else>{{ change > 0 ? 'На конец периода денег станет больше на' : 'На конец периода денег станет меньше на' }} <strong class="num">{{ rub(Math.abs(change)) }}</strong>.</p>
            </div>
            <BalanceChart :history="history" :points="base.points" :threshold="base.threshold"
                          :compare="result.points" compare-label="После события" forecast-label="Сейчас" />
            <dl class="comparison">
              <div><dt>Без события, на {{ humanDate(lastDay) }}</dt><dd class="num">{{ rub(base.points.at(-1)!.p50) }}</dd></div>
              <div><dt>После события</dt><dd class="num">{{ rub(result.points.at(-1)!.p50) }}</dd></div>
            </dl>
            <p class="hint">Обе линии учитывают обычный разброс поступлений и расходов. Уверенность в событии учтена при расчёте.</p>
          </template>
        </section>
      </div>
    </div>
  </dialog>
</template>

<style scoped>
.draft { width: min(1060px, calc(100% - 32px)); max-width: none; max-height: calc(100dvh - 32px); padding: 0; border: 0; border-radius: var(--radius-l); color: var(--ink); background: var(--surface); box-shadow: 0 16px 64px rgb(19 36 29 / 0.2); }
.draft::backdrop { background: rgb(19 36 29 / 0.4); }
.draft-content { padding: 24px; }
.draft-head { display: flex; align-items: start; justify-content: space-between; gap: 20px; margin-bottom: 24px; }
.draft-head h2 { font-size: 24px; }
.draft-head p { color: var(--ink-2); max-width: 65ch; margin: 8px 0 0; }
.close { flex-shrink: 0; }
.draft-layout { display: grid; grid-template-columns: minmax(0, 310px) minmax(0, 1fr); gap: 28px; }
fieldset { min-width: 0; border: 0; margin: 0; padding: 0; }
.direction { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 16px; }
.direction .btn { padding-inline: 6px; }
.direction .on { border-color: var(--green); background: var(--green-wash); color: var(--green); }
.field input, .field select { min-width: 0; width: 100%; }
.hint { font-size: 13px; line-height: 1.5; color: var(--ink-2); }
#draft-period { margin: -4px 0 16px; }
.save-note { margin-bottom: 0; }
.actions { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px; margin-top: 20px; }
.btn:disabled { opacity: 0.6; cursor: wait; }
.preview { min-width: 0; padding: 20px; border-radius: var(--radius-l); background: var(--paper); }
.preview-empty { min-height: 320px; display: flex; flex-direction: column; justify-content: center; }
.preview h3 { font-size: 21px; line-height: 1.3; text-wrap: balance; }
.preview p { color: var(--ink-2); }
.preview-summary:focus { outline: 0; }
.preview-summary p { margin-bottom: 0; }
.comparison { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; padding-top: 16px; margin: 0; border-top: 1px solid var(--line); }
.comparison dt { font-size: 13px; color: var(--ink-2); }
.comparison dd { font-size: 20px; margin: 4px 0 0; }
.visually-hidden { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; border: 0; }
@media (max-width: 760px) {
  .draft-content { padding: 18px; }
  .draft-head { gap: 12px; margin-bottom: 20px; }
  .draft-head h2 { font-size: 21px; }
  .close { padding-inline: 8px; font-size: 13px; }
  .draft-layout { grid-template-columns: minmax(0, 1fr); gap: 20px; }
  .preview { padding: 16px; }
  .preview-empty { min-height: 160px; }
  .comparison { grid-template-columns: 1fr; gap: 12px; }
}
</style>
