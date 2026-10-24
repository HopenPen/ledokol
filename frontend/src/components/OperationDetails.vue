<script setup lang="ts">
// Раскрытая операция: детали, документы (чек и сопутствующие), смена категории и прогноз без этой операции.
import { Calculator, Check } from 'lucide-vue-next'
import { computed, inject, ref, type Ref } from 'vue'
import { api, ApiError, type Dashboard, type Forecast, type Operation } from '../api'
import { CATEGORY_SOURCE, humanDate, money, rub } from '../format'
import AttachmentsBlock from './AttachmentsBlock.vue'
import BalanceChart from './BalanceChart.vue'

const props = defineProps<{ op: Operation; companyId: string; categories: { code: string; label: string }[] }>()
const emit = defineEmits<{ (e: 'categoryChanged', count: number): void }>()
const dashboard = inject<Ref<Dashboard | null>>('dashboard')!

// --- категория ---
const category = ref(props.op.category)
const applyAll = ref(true)
const savingCat = ref(false)
const catError = ref('')
async function saveCategory() {
  if (savingCat.value || category.value === props.op.category) return
  savingCat.value = true
  catError.value = ''
  try {
    const changed = await api.patchCategory(props.op.id, category.value, applyAll.value)
    emit('categoryChanged', changed.length)
  } catch (e) { catError.value = e instanceof ApiError ? e.message : 'Не удалось сменить категорию' }
  finally { savingCat.value = false }
}

// --- прогноз без операции ---
const preview = ref<Forecast | null>(null)
const previewBusy = ref(false)
const previewError = ref('')
async function runPreview() {
  previewBusy.value = true
  previewError.value = ''
  try { preview.value = await api.preview(props.companyId, { exclude_operation_ids: [props.op.id] }) }
  catch (e) { previewError.value = e instanceof ApiError ? e.message : 'Не удалось пересчитать прогноз' }
  finally { previewBusy.value = false }
}
const base = computed(() => dashboard.value?.forecast ?? null)
const minOf = (f: Forecast) => Math.min(...f.points.map((p) => p.p50))
const firstGap = (f: Forecast) => f.alerts.find((a) => !a.worst_case)?.start ?? null
const diff = computed(() => {
  if (!preview.value || !base.value) return null
  const b = minOf(base.value)
  const p = minOf(preview.value)
  return { baseMin: b, newMin: p, delta: p - b, baseGap: firstGap(base.value), newGap: firstGap(preview.value) }
})
const QUALITY: Record<string, string> = { duplicate: 'Дубль выгрузки: в остатке не учитывается', after_gap: 'Первая операция после пропуска в выписке' }
</script>

<template>
  <div class="details">
    <dl class="meta">
      <div class="m-wide"><dt>Назначение платежа</dt><dd>{{ op.purpose || '—' }}</dd></div>
      <div><dt>Контрагент</dt><dd>{{ op.counterparty_name }}<span v-if="op.counterparty_inn" class="tiny"> · ИНН {{ op.counterparty_inn }}</span></dd></div>
      <div><dt>Остаток на конец дня</dt><dd class="num">{{ op.balance_eod === null ? 'Неизвестен' : money(op.balance_eod) }}</dd></div>
      <div><dt>Откуда операция</dt><dd>{{ op.source === 'manual' ? 'Добавлена вручную' : 'Банковская выписка' }}</dd></div>
      <div v-if="QUALITY[op.quality]" class="m-wide"><dt>Качество данных</dt><dd class="warn-text">{{ QUALITY[op.quality] }}</dd></div>
    </dl>

    <div class="cols">
      <section class="block" :aria-labelledby="`docs-${op.id}`">
        <h4 :id="`docs-${op.id}`">Документы</h4>
        <AttachmentsBlock :operation-id="op.id" />
      </section>

      <section class="block" :aria-labelledby="`cat-${op.id}`">
        <h4 :id="`cat-${op.id}`">Категория</h4>
        <p class="small muted">Сейчас: <b class="ink">{{ op.category_label }}</b>, {{ CATEGORY_SOURCE[op.category_source] ?? op.category_source }}.</p>
        <label class="field compact">Новая категория
          <select v-model="category">
            <option v-for="c in categories" :key="c.code" :value="c.code">{{ c.label }}</option>
          </select>
        </label>
        <label class="check"><input v-model="applyAll" type="checkbox" />
          <span>Применить ко всем платежам этого контрагента с той же категорией</span></label>
        <button class="btn btn-sm save" :disabled="savingCat || category === op.category" @click="saveCategory">
          <Check />{{ savingCat ? 'Сохраняем…' : 'Сохранить категорию' }}
        </button>
        <p v-if="catError" class="error">{{ catError }}</p>
      </section>

      <section class="block wide" :aria-labelledby="`pv-${op.id}`">
        <h4 :id="`pv-${op.id}`">Прогноз без этой операции</h4>
        <p v-if="!preview" class="small muted">Посмотрите, как изменится прогноз, если не учитывать этот платёж. Данные не меняются.</p>
        <button v-if="!preview" class="btn btn-sm" :disabled="previewBusy" @click="runPreview">
          <Calculator />{{ previewBusy ? 'Считаем…' : 'Посчитать' }}
        </button>
        <p v-if="previewError" class="error">{{ previewError }}</p>
        <template v-if="preview && diff">
          <p class="pv-head">{{ preview.headline }}</p>
          <dl class="pv">
            <div><dt>Минимум остатка</dt>
              <dd class="num">{{ rub(diff.newMin) }} <span class="tiny">({{ diff.delta >= 0 ? '+' : '−' }}{{ rub(Math.abs(diff.delta)) }} к текущему)</span></dd></div>
            <div><dt>Первая нехватка</dt>
              <dd>{{ diff.newGap ? humanDate(diff.newGap) : 'не видно' }}
                <span class="tiny">(сейчас {{ diff.baseGap ? humanDate(diff.baseGap) : 'не видно' }})</span></dd></div>
          </dl>
          <BalanceChart v-if="dashboard && base" :history="dashboard.history" :points="base.points" :threshold="base.threshold"
                        :compare="preview.points" compare-label="Без этой операции" :height="220" :history-days="30" />
          <button class="btn btn-ghost btn-sm" @click="preview = null">Скрыть</button>
        </template>
      </section>
    </div>
  </div>
</template>

<style scoped>
.details { display: grid; gap: 20px; padding: 4px 0 8px; }
.meta { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px 24px; margin: 0; }
.meta dt { font-size: 13px; color: var(--ink-3); }
.meta dd { margin: 2px 0 0; font-size: 14px; overflow-wrap: anywhere; }
.m-wide { grid-column: 1 / -1; }
.warn-text { color: var(--warn); }
.cols { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 16px; }
.wide { grid-column: 1 / -1; }
.block { background: var(--bg); border-radius: var(--radius); padding: 16px; display: grid; gap: 10px; align-content: start; min-width: 0; }
h4 { font-size: 15px; }
.ink { color: var(--ink); }
.compact { margin-bottom: 0; }
.save { justify-self: start; }
.pv-head { font-weight: 600; font-size: 15px; }
.pv { margin: 0; display: grid; gap: 6px; }
.pv dt { font-size: 13px; color: var(--ink-3); }
.pv dd { margin: 0; font-size: 14px; }
@media (max-width: 900px) { .cols { grid-template-columns: 1fr; } }
@media (max-width: 640px) { .meta { grid-template-columns: 1fr; } }
</style>
