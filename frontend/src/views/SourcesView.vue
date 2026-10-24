<script setup lang="ts">
// «Откуда приложение знает о ваших деньгах»: выписка, 1С, ФНС, налоги, ручные события, настройки.
import { inject, onMounted, ref, type Ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, ApiError, type Dashboard, type EventRow } from '../api'
import { humanDate, rub } from '../format'

const route = useRoute()
const id = route.params.id as string
const dashboard = inject<Ref<Dashboard | null>>('dashboard')!
const reload = inject<() => Promise<void>>('reload')!
const events = ref<EventRow[]>([])
const msg = ref<Record<string, string>>({})
const risky = ref<{ inn: string; status: string; has_tax_debt: boolean }[]>([])
const settings = ref({ name: '', industry: '', tax_regime: 'unknown', min_balance: '0' })

onMounted(async () => {
  events.value = (await api.events(id)).filter((e) => e.source === 'manual' && e.status === 'expected')
  const c = dashboard.value?.company
  if (c) settings.value = { name: c.name, industry: c.industry ?? '', tax_regime: c.tax_regime, min_balance: c.min_balance }
})

async function run(key: string, fn: () => Promise<string>) {
  msg.value[key] = 'Выполняем…'
  try { msg.value[key] = await fn(); await reload() } catch (e) { msg.value[key] = e instanceof ApiError ? e.message : 'Ошибка' }
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
const save = () => run('settings', async () => { await api.patchCompany(id, settings.value); return 'Сохранено' })
async function removeEvent(e: EventRow) {
  await api.deleteEvent(id, e.id)
  events.value = events.value.filter((x) => x.id !== e.id)
  await reload()
}
async function onFile(ev: Event) {
  const file = (ev.target as HTMLInputElement).files?.[0]
  if (file) run('statement', async () => { await api.uploadStatement(id, file); return 'Выписка загружена' })
}
</script>

<template>
  <div class="grid">
    <section class="card">
      <h2>Банковская выписка</h2>
      <p v-if="dashboard" class="muted">Данные по {{ humanDate(dashboard.forecast.as_of) }}</p>
      <p v-for="w in dashboard?.forecast.warnings ?? []" :key="w" class="warn">{{ w }}</p>
      <label class="btn">Загрузить выписку<input type="file" accept=".csv" hidden @change="onFile" /></label>
      <p class="msg">{{ msg.statement }}</p>
    </section>

    <section class="card">
      <h2>1С: счета</h2>
      <p class="muted">Неоплаченные счета клиентам и поставщикам попадают в прогноз как ожидаемые платежи.</p>
      <button class="btn" @click="sync1c">Синхронизировать</button>
      <p class="msg">{{ msg['1c'] }}</p>
    </section>

    <section class="card">
      <h2>ФНС: проверка контрагентов</h2>
      <p class="muted">Если клиент в ликвидации или с долгом перед налоговой, его оплата считается менее вероятной.</p>
      <button class="btn" @click="syncFns">Проверить контрагентов</button>
      <p class="msg">{{ msg.fns }}</p>
      <ul v-if="risky.length"><li v-for="r in risky" :key="r.inn">ИНН {{ r.inn }}: {{ r.status === 'liquidating' ? 'в ликвидации' : 'долг перед налоговой' }}</li></ul>
    </section>

    <section class="card">
      <h2>Ваши события</h2>
      <p v-if="!events.length" class="muted">Вы пока ничего не добавляли вручную.</p>
      <ul class="events">
        <li v-for="e in events" :key="e.id">
          <span>{{ humanDate(e.event_date) }} · {{ e.title }} · {{ e.direction === 'in' ? '+' : '−' }}{{ rub(Number(e.amount)) }}</span>
          <button class="btn" @click="removeEvent(e)">Убрать</button>
        </li>
      </ul>
    </section>

    <form class="card" @submit.prevent="save">
      <h2>Налоги и настройки</h2>
      <label class="field">Название <input v-model="settings.name" maxlength="200" /></label>
      <label class="field">Отрасль <input v-model="settings.industry" maxlength="100" /></label>
      <label class="field">Режим налогообложения
        <select v-model="settings.tax_regime">
          <option value="unknown">Не знаю</option><option value="usn">УСН</option>
          <option value="osno">ОСНО</option><option value="eskhn">ЕСХН</option>
        </select>
      </label>
      <label class="field">Неснижаемый остаток, ₽ — предупреждать, если денег станет меньше
        <input v-model="settings.min_balance" type="number" min="0" />
      </label>
      <button class="btn btn-primary">Сохранить</button>
      <p class="msg">{{ msg.settings }}</p>
    </form>
  </div>
</template>

<style scoped>
.grid { display: grid; gap: 16px; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); align-items: start; }
h2 { font-size: 18px; margin-bottom: 6px; }
.muted { color: var(--muted); font-size: 14px; }
.warn { color: var(--warn); font-size: 14px; }
.msg { color: var(--ink-2); font-size: 14px; min-height: 1.5em; }
.events { list-style: none; padding: 0; }
.events li { display: flex; justify-content: space-between; gap: 8px; align-items: center; padding: 6px 0; border-top: 1px solid var(--line); }
</style>
