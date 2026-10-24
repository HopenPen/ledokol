<script setup lang="ts">
// Операции: поиск и фильтр на сервере, строка раскрывается в карточку с документами,
// сменой категории и прогнозом без этой операции.
import { ChevronDown, Plus, Search } from 'lucide-vue-next'
import { inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, ApiError, type ImportResult, type Operation } from '../api'
import AddPaymentModal from '../components/AddPaymentModal.vue'
import OperationDetails from '../components/OperationDetails.vue'
import StatementUpload from '../components/StatementUpload.vue'
import { importSummary, shortDate, signed } from '../format'

const PAGE = 50
const route = useRoute()
const id = route.params.id as string
const reload = inject<() => Promise<void>>('reload')!
const toast = inject<(t: string) => void>('toast')!
const ops = ref<Operation[]>([])
const categories = ref<{ code: string; label: string }[]>([])
const query = ref('')
const category = ref('')
const loading = ref(true)
const more = ref(false)
const error = ref('')
const adding = ref(false)
const expanded = ref<string | null>(null)
let seq = 0

async function load(append = false) {
  const my = ++seq                       // ответ на устаревший запрос не перетирает свежий
  loading.value = true
  error.value = ''
  try {
    const page = await api.searchOperations(id, query.value.trim(), category.value, append ? ops.value.length : 0, PAGE)
    if (my !== seq) return
    ops.value = append ? [...ops.value, ...page] : page
    more.value = page.length === PAGE
  } catch (e) {
    if (my === seq) error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить операции'
  } finally {
    if (my === seq) loading.value = false
  }
}

let debounce: number | undefined
onBeforeUnmount(() => { window.clearTimeout(debounce); ++seq })
watch(query, () => { window.clearTimeout(debounce); debounce = window.setTimeout(() => load(), 300) })
watch(category, () => load())
onMounted(async () => {
  try { categories.value = await api.categories() } catch { /* фильтр без категорий переживём */ }
  await load()
})

function toggle(op: Operation) { expanded.value = expanded.value === op.id ? null : op.id }

async function afterImport(results: ImportResult[]) {
  toast(importSummary(results))
  await Promise.all([load(), reload()])
}
async function afterPayment(warning: string) {
  adding.value = false
  toast(warning || 'Платёж добавлен. Прогноз обновлён')
  query.value = ''
  category.value = ''
  await Promise.all([load(), reload()])
}
async function afterCategory(count: number) {
  toast(`Категория изменена у ${count} ${count === 1 ? 'операции' : 'операций'}. Прогноз обновлён`)
  await Promise.all([load(), reload()])
}
const QUALITY_HINT: Record<string, string> = { duplicate: 'дубль', after_gap: 'после пропуска' }
</script>

<template>
  <section class="ops">
    <div class="head">
      <div>
        <h1>Операции</h1>
        <p class="muted small">Нажмите на операцию, чтобы прикрепить чек и документы, сменить категорию или посмотреть прогноз без неё.</p>
      </div>
      <div class="head-actions">
        <StatementUpload :company-id="id" @imported="afterImport" @error="toast" />
        <button class="btn btn-primary" @click="adding = true"><Plus />Добавить платёж</button>
      </div>
    </div>

    <div class="toolbar">
      <label class="search">
        <Search aria-hidden="true" />
        <span class="visually-hidden">Поиск по контрагенту, назначению или категории</span>
        <input v-model="query" class="input" type="search" maxlength="120" placeholder="Контрагент, назначение или категория" />
      </label>
      <label class="filter">
        <span class="visually-hidden">Категория</span>
        <select v-model="category" class="input">
          <option value="">Все категории</option>
          <option v-for="c in categories" :key="c.code" :value="c.code">{{ c.label }}</option>
        </select>
      </label>
    </div>

    <p v-if="error" class="error" role="alert">{{ error }}</p>

    <div class="list card" :aria-busy="loading">
      <p v-if="!loading && !ops.length" class="state">
        {{ query || category ? 'Ничего не нашлось. Попробуйте другой запрос.' : 'Операций пока нет. Загрузите выписку или добавьте платёж.' }}
      </p>
      <article v-for="op in ops" :key="op.id" class="row" :class="{ open: expanded === op.id, dim: op.quality === 'duplicate' }">
        <button class="row-head" :aria-expanded="expanded === op.id" :aria-controls="`op-${op.id}`" @click="toggle(op)">
          <span class="r-date num">{{ shortDate(op.op_date) }}</span>
          <span class="r-main">
            <span class="r-name">{{ op.counterparty_name }}</span>
            <span class="r-purpose">{{ op.purpose || 'Без назначения' }}</span>
          </span>
          <span class="r-tags">
            <span class="chip">{{ op.category_label }}</span>
            <span v-if="op.source === 'manual'" class="chip chip-brand">вручную</span>
            <span v-if="QUALITY_HINT[op.quality]" class="chip chip-warn">{{ QUALITY_HINT[op.quality] }}</span>
          </span>
          <span class="amount r-amt" :class="op.direction">{{ signed(op.amount, op.direction) }}</span>
          <ChevronDown class="r-chev" aria-hidden="true" />
        </button>
        <div v-if="expanded === op.id" :id="`op-${op.id}`" class="row-body">
          <OperationDetails :op="op" :company-id="id" :categories="categories" @category-changed="afterCategory" />
        </div>
      </article>
      <div v-if="loading" class="rows-loading">
        <div v-for="i in 4" :key="i" class="skeleton" style="height: 52px" />
      </div>
    </div>
    <button v-if="more && !loading" class="btn more" @click="load(true)">Показать ещё</button>

    <AddPaymentModal v-if="adding" :company-id="id" @close="adding = false" @saved="afterPayment" />
  </section>
</template>

<style scoped>
.ops { display: grid; gap: 16px; }
.head { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap; }
.head h1 { margin-bottom: 4px; }
.head-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.toolbar { display: grid; grid-template-columns: minmax(0, 1fr) 260px; gap: 12px; }
.search { position: relative; }
.search svg { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); width: 18px; height: 18px; color: var(--ink-3); pointer-events: none; }
.search input { padding-left: 40px; }
.list { padding: 0; overflow: hidden; }
.state { padding: 24px; }
.row + .row { border-top: 1px solid var(--line); }
.row.open { background: var(--surface); box-shadow: inset 3px 0 0 var(--brand); }
.row.dim .row-head { opacity: 0.6; }
.row-head {
  width: 100%; display: grid; grid-template-columns: 64px minmax(0, 1fr) auto 150px 20px; gap: 16px; align-items: center;
  padding: 14px 20px; background: none; border: 0; text-align: left; cursor: pointer; font-size: 15px;
}
.row-head:hover { background: var(--bg); }
.r-date { color: var(--ink-2); font-size: 14px; }
.r-main { display: grid; min-width: 0; }
.r-name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.r-purpose { color: var(--ink-3); font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.r-tags { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
.r-amt { text-align: right; font-weight: 650; white-space: nowrap; }
.r-chev { width: 18px; height: 18px; color: var(--ink-3); transition: transform 150ms; }
.open .r-chev { transform: rotate(180deg); }
.row-body { padding: 0 20px 20px 100px; }
.rows-loading { display: grid; gap: 8px; padding: 12px 20px; }
.more { justify-self: center; }
@media (max-width: 900px) {
  .row-head { grid-template-columns: minmax(0, 1fr) auto 20px; grid-template-areas: 'm a c' 't d c'; gap: 4px 12px; padding: 12px 16px; }
  .r-main { grid-area: m; } .r-amt { grid-area: a; } .r-chev { grid-area: c; }
  .r-tags { grid-area: t; justify-content: flex-start; } .r-date { grid-area: d; text-align: right; }
  .row-body { padding: 0 16px 16px; }
  .toolbar { grid-template-columns: 1fr; }
}
</style>
