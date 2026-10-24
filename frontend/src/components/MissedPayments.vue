<script setup lang="ts">
// «Платёж не пришёл в срок» (план-факт): предупреждаем и даём два действия —
// ждать до новой даты или больше не ждать. Прогноз после этого пересчитывается.
import { CircleAlert } from 'lucide-vue-next'
import { ref } from 'vue'
import { api, ApiError, type EventRow } from '../api'
import { humanDate, money } from '../format'

const props = defineProps<{ companyId: string; events: EventRow[]; minDate: string }>()
const emit = defineEmits<{ (e: 'changed'): void }>()
const editing = ref<string | null>(null)
const newDate = ref('')
const busy = ref(false)
const error = ref('')

async function reschedule(ev: EventRow) {
  if (!newDate.value || busy.value) return
  busy.value = true
  error.value = ''
  try { await api.patchEvent(props.companyId, ev.id, { event_date: newDate.value }); editing.value = null; emit('changed') }
  catch (e) { error.value = e instanceof ApiError ? e.message : 'Не удалось перенести платёж' }
  finally { busy.value = false }
}

async function drop(ev: EventRow) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try { await api.patchEvent(props.companyId, ev.id, { status: 'cancelled' }); emit('changed') }
  catch (e) { error.value = e instanceof ApiError ? e.message : 'Не удалось отменить платёж' }
  finally { busy.value = false }
}
</script>

<template>
  <section v-if="events.length" class="missed" aria-live="polite">
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <h2><CircleAlert aria-hidden="true" />Не пришли в срок</h2>
    <article v-for="ev in events" :key="ev.id" class="item">
      <p><b>{{ ev.title }}</b> · <span class="num">{{ money(ev.amount) }}</span>, ждали {{ humanDate(ev.event_date) }}.
        Эти деньги убраны из прогноза.</p>
      <div v-if="editing === ev.id" class="row">
        <input v-model="newDate" class="input date" type="date" :min="minDate" aria-label="Новая дата" />
        <button class="btn btn-primary btn-sm" :disabled="!newDate || busy" @click="reschedule(ev)">Ждать до этой даты</button>
        <button class="btn btn-ghost btn-sm" @click="editing = null">Отмена</button>
      </div>
      <div v-else class="row">
        <button class="btn btn-sm" @click="editing = ev.id; newDate = ''">Клиент обещал позже</button>
        <button class="btn btn-ghost btn-sm" :disabled="busy" @click="drop(ev)">Больше не ждать</button>
      </div>
    </article>
  </section>
</template>

<style scoped>
.missed { background: var(--risk-soft); border: 1px solid var(--risk-line); border-radius: var(--radius); padding: 16px 20px; display: grid; gap: 12px; }
h2 { font-size: 16px; color: var(--risk); display: flex; align-items: center; gap: 8px; }
h2 svg { width: 20px; height: 20px; }
.item { display: grid; gap: 8px; }
.row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.date { width: auto; min-height: 32px; padding: 4px 8px; font-size: 14px; }
</style>
