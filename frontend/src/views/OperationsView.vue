<script setup lang="ts">
import { inject, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, type Operation } from '../api'
import { humanDate, rub } from '../format'

const route = useRoute()
const reload = inject<() => Promise<void>>('reload')!
const ops = ref<Operation[]>([])
const categories = ref<{ code: string; label: string }[]>([])
const filter = ref('')
const offset = ref(0)
const editing = ref<string | null>(null)
const applyAll = ref(true)
const toast = ref('')
const SOURCE = { rule: 'правило', counterparty: 'по контрагенту', ml: 'модель', user: 'вы', none: '—' } as Record<string, string>

async function load() { ops.value = await api.operations(route.params.id as string, offset.value, filter.value) }
onMounted(async () => { categories.value = await api.categories(); await load() })
watch([filter, offset], load)

async function setCategory(op: Operation, code: string) {
  const changed = await api.patchCategory(op.id, code, applyAll.value)
  editing.value = null
  toast.value = `Категория изменена у ${changed.length} операций — прогноз обновлён`
  await Promise.all([load(), reload()])
}
</script>

<template>
  <section class="card">
    <header class="head">
      <h2>Операции</h2>
      <select v-model="filter" aria-label="Фильтр по категории" @change="offset = 0">
        <option value="">Все категории</option>
        <option v-for="c in categories" :key="c.code" :value="c.code">{{ c.label }}</option>
      </select>
    </header>
    <p v-if="toast" class="toast" role="status">{{ toast }}</p>
    <div class="scroll">
      <table>
        <thead><tr><th>Дата</th><th>Контрагент</th><th>Назначение</th><th class="r">Сумма</th><th>Категория</th></tr></thead>
        <tbody>
          <tr v-for="op in ops" :key="op.id" :class="{ dim: op.quality !== 'ok' }"
              :title="op.quality === 'duplicate' ? 'Дубль выгрузки — не учитывается' : op.quality === 'after_gap' ? 'После пропуска в выписке' : ''">
            <td class="num">{{ humanDate(op.op_date) }}</td>
            <td>{{ op.counterparty_name }}</td>
            <td class="purpose" :title="op.purpose">{{ op.purpose }}</td>
            <td class="r num" :class="op.direction">{{ op.direction === 'in' ? '+' : '−' }}{{ rub(Number(op.amount)) }}</td>
            <td>
              <template v-if="editing === op.id">
                <select :value="op.category" @change="setCategory(op, ($event.target as HTMLSelectElement).value)">
                  <option v-for="c in categories" :key="c.code" :value="c.code">{{ c.label }}</option>
                </select>
                <label class="all"><input v-model="applyAll" type="checkbox" /> ко всем операциям контрагента</label>
              </template>
              <button v-else class="badge as-btn" @click="editing = op.id">{{ op.category_label }}</button>
              <span class="src">{{ SOURCE[op.category_source] }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="pager">
      <button class="btn" :disabled="offset === 0" @click="offset = Math.max(0, offset - 100)">Назад</button>
      <button class="btn" :disabled="ops.length < 100" @click="offset += 100">Дальше</button>
    </div>
  </section>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 12px; }
.scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th { text-align: left; color: var(--muted); font-weight: 500; padding: 6px 8px; border-bottom: 1px solid var(--line); }
td { padding: 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
.r { text-align: right; white-space: nowrap; }
.in { color: var(--green); }
.purpose { max-width: 360px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink-2); }
.dim { opacity: 0.5; }
.as-btn { border: 0; cursor: pointer; }
.src { display: block; color: var(--muted); font-size: 12px; }
.all { display: block; font-size: 12px; color: var(--ink-2); }
.pager { display: flex; gap: 8px; justify-content: flex-end; margin-top: 12px; }
.toast { color: var(--green); }
</style>
