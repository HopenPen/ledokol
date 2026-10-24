<script setup lang="ts">
// Источники: откуда сервис знает о ваших деньгах. Выписка, 1С, ФНС, налоговый календарь, ваши события, настройки.
// 1С и ФНС в прототипе — отдельные сервисы-имитаторы; так и подписываем, не выдаём за боевые интеграции.
import { CalendarPlus, Landmark, RefreshCw, ShieldCheck, Trash2 } from 'lucide-vue-next'
import { inject, onMounted, ref, watch, type Ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, ApiError, type Company, type Dashboard, type EventRow, type ImportResult } from '../api'
import AddEventModal from '../components/AddEventModal.vue'
import StatementUpload from '../components/StatementUpload.vue'
import { humanDate, importSummary, signed, SOURCE_LABEL } from '../format'

const route = useRoute()
const id = route.params.id as string
const dashboard = inject<Ref<Dashboard | null>>('dashboard')!
const company = inject<Ref<Company | null>>('company')!
const reload = inject<() => Promise<void>>('reload')!
const toast = inject<(t: string) => void>('toast')!
const events = ref<EventRow[]>([])
const msg = ref<Record<string, string>>({})
const busy = ref<Record<string, boolean>>({})
const risky = ref<{ inn: string; status: string; has_tax_debt: boolean }[]>([])
const settings = ref({ name: '', industry: '', tax_regime: 'unknown', min_balance: '0' })
const addingEvent = ref(false)
const today = new Intl.DateTimeFormat('sv-SE').format(new Date())

async function loadEvents() {
  try { events.value = (await api.events(id)).filter((e) => e.source === 'manual' && e.status === 'expected') } catch { events.value = [] }
}
onMounted(loadEvents)
watch(company, (c) => {
  if (c) settings.value = { name: c.name, industry: c.industry ?? '', tax_regime: c.tax_regime, min_balance: String(Number(c.min_balance)) }
}, { immediate: true })

async function run(key: string, fn: () => Promise<string>) {
  busy.value[key] = true
  msg.value[key] = ''
  try { msg.value[key] = await fn(); await reload() }
  catch (e) { msg.value[key] = e instanceof ApiError ? e.message : 'Сервис недоступен, попробуйте позже' }
  finally { busy.value[key] = false }
}
const sync1c = () => run('1c', async () => {
  const r = await api.sync1c(id)
  return `Новых счетов: ${r.created}, обновлено: ${r.updated}, оплачено с прошлого раза: ${r.closed}`
})
const syncFns = () => run('fns', async () => {
  const r = await api.syncFns(id)
  risky.value = r.filter((x) => x.risky)
  return `Проверено контрагентов: ${r.length}, с риском: ${risky.value.length}`
})
const save = () => run('settings', async () => { await api.patchCompany(id, settings.value); return 'Сохранено, прогноз пересчитан' })

async function removeEvent(e: EventRow) {
  try { await api.deleteEvent(id, e.id); events.value = events.value.filter((x) => x.id !== e.id); await reload(); toast('Платёж убран из прогноза') }
  catch (err) { toast(err instanceof ApiError ? err.message : 'Не удалось убрать платёж') }
}
async function eventSaved() { addingEvent.value = false; await Promise.all([loadEvents(), reload()]); toast('Платёж добавлен в прогноз') }
async function afterImport(results: ImportResult[]) {
  toast(importSummary(results))
  await reload()
}
</script>

<template>
  <div class="src-page">
    <div class="intro">
      <h1>Источники данных</h1>
      <p class="muted small">Откуда сервис знает о ваших деньгах. У каждого будущего платежа в прогнозе есть метка источника:</p>
      <p class="legend">
        <span v-for="(label, key) in SOURCE_LABEL" :key="key" class="src" :class="`src-${key}`">{{ label }}</span>
      </p>
    </div>

    <div class="grid">
      <section class="card">
        <div class="card-head"><h2>Банковская выписка</h2><span class="chip chip-brand">основной источник</span></div>
        <p v-if="dashboard" class="small muted">Данные по {{ humanDate(dashboard.forecast.as_of, true) }}. Новая выписка дополнит историю без дублей.</p>
        <p v-for="w in dashboard?.forecast.warnings ?? []" :key="w" class="small warn">{{ w }}</p>
        <StatementUpload :company-id="id" @imported="afterImport" @error="toast" />
      </section>

      <section class="card">
        <div class="card-head"><h2>Ваши ожидаемые платежи</h2></div>
        <p v-if="!events.length" class="small muted">Вы пока ничего не добавляли. Например: «клиент обещал 300 000 ₽ 20-го».</p>
        <ul class="events">
          <li v-for="e in events" :key="e.id">
            <span class="e-main"><b>{{ e.title }}</b><span class="tiny">{{ humanDate(e.event_date) }}</span></span>
            <span class="amount" :class="e.direction">{{ signed(e.amount, e.direction) }}</span>
            <button class="btn btn-ghost btn-icon" :aria-label="`Убрать ${e.title}`" @click="removeEvent(e)"><Trash2 /></button>
          </li>
        </ul>
        <button class="btn" @click="addingEvent = true"><CalendarPlus />Добавить ожидаемый платёж</button>
      </section>

      <section class="card">
        <div class="card-head"><h2>1С: выставленные счета</h2><span class="chip">имитатор</span></div>
        <p class="small muted">Неоплаченные счета клиентам и поставщикам попадают в прогноз как ожидаемые платежи с меткой «1С».</p>
        <button class="btn" :disabled="busy['1c']" @click="sync1c"><RefreshCw />{{ busy['1c'] ? 'Синхронизируем…' : 'Синхронизировать' }}</button>
        <p class="small msg" role="status">{{ msg['1c'] }}</p>
      </section>

      <section class="card">
        <div class="card-head"><h2>ФНС: проверка контрагентов</h2><span class="chip">имитатор</span></div>
        <p class="small muted">Если клиент в ликвидации или с долгом перед налоговой, его оплата считается менее вероятной.</p>
        <button class="btn" :disabled="busy.fns" @click="syncFns"><ShieldCheck />{{ busy.fns ? 'Проверяем…' : 'Проверить контрагентов' }}</button>
        <p class="small msg" role="status">{{ msg.fns }}</p>
        <ul v-if="risky.length" class="risky">
          <li v-for="r in risky" :key="r.inn">ИНН {{ r.inn }}: {{ r.status === 'liquidating' ? 'в ликвидации' : 'долг перед налоговой' }}</li>
        </ul>
      </section>

      <form class="card" @submit.prevent="save">
        <div class="card-head"><h2>Компания и налоги</h2><Landmark class="h-ico" aria-hidden="true" /></div>
        <label class="field">Название <input v-model="settings.name" maxlength="200" /></label>
        <label class="field">Отрасль <input v-model="settings.industry" maxlength="100" placeholder="Например, общепит" /></label>
        <label class="field">Система налогообложения
          <select v-model="settings.tax_regime">
            <option value="unknown">Не знаю</option><option value="usn">УСН</option>
            <option value="osno">ОСНО</option><option value="eskhn">ЕСХН</option>
          </select>
          <span class="hint">Налоги в прогнозе считаются по календарю 2026 года: ЕНП до 28-го числа</span>
        </label>
        <label class="field">Неснижаемый остаток, ₽
          <input v-model="settings.min_balance" type="number" inputmode="decimal" min="0" />
          <span class="hint">Предупредим, если прогноз опустится ниже этой суммы</span>
        </label>
        <button class="btn btn-primary" :disabled="busy.settings">{{ busy.settings ? 'Сохраняем…' : 'Сохранить' }}</button>
        <p class="small msg" role="status">{{ msg.settings }}</p>
      </form>
    </div>
    <AddEventModal v-if="addingEvent" :company-id="id" :min-date="dashboard?.forecast.as_of ?? today" @close="addingEvent = false" @saved="eventSaved" />
  </div>
</template>

<style scoped>
.src-page { display: grid; gap: 16px; }
.intro h1 { margin-bottom: 4px; }
.legend { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.grid { display: grid; gap: 16px; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); align-items: start; }
.card { display: grid; gap: 12px; align-content: start; justify-items: start; }
.card-head { width: 100%; margin-bottom: 0; }
.card .field { width: 100%; }
.h-ico { width: 20px; height: 20px; color: var(--ink-3); }
.warn { color: var(--warn); }
.msg { color: var(--ink-2); min-height: 1.4em; }
.events { list-style: none; padding: 0; margin: 0; width: 100%; }
.events li { display: flex; align-items: center; gap: 12px; padding: 8px 0; border-top: 1px solid var(--line); }
.e-main { flex: 1; display: grid; min-width: 0; }
.amount { font-weight: 600; white-space: nowrap; }
.risky { margin: 0; padding-left: 18px; font-size: 14px; color: var(--risk); }
</style>
