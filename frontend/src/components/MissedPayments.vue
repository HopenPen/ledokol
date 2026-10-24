<script setup lang="ts">
// «Платёж не пришёл в срок» (звёздочка 2): предупреждаем и даём два действия —
// перенести ожидание на новую дату или перестать ждать. Прогноз после этого пересчитается.
import { ref } from 'vue'
import { api, type EventRow } from '../api'
import { humanDate, rub } from '../format'

const props = defineProps<{ companyId: string; events: EventRow[]; minDate: string }>()
const emit = defineEmits<{ (e: 'changed'): void }>()
const editing = ref<string | null>(null)
const newDate = ref('')

async function reschedule(ev: EventRow) {
  if (!newDate.value) return
  await api.patchEvent(props.companyId, ev.id, { event_date: newDate.value })
  editing.value = null
  emit('changed')
}

async function drop(ev: EventRow) {
  await api.patchEvent(props.companyId, ev.id, { status: 'cancelled' })
  emit('changed')
}
</script>

<template>
  <section v-if="events.length" class="missed" aria-live="polite">
    <h2>Не пришли в срок</h2>
    <article v-for="ev in events" :key="ev.id" class="item">
      <p>
        <strong>{{ ev.title }}</strong> — {{ rub(Number(ev.amount)) }}, ждали {{ humanDate(ev.event_date) }}.
        Из прогноза эти деньги убраны.
      </p>
      <div v-if="editing === ev.id" class="row">
        <input v-model="newDate" type="date" :min="minDate" aria-label="Новая дата ожидания" />
        <button class="btn btn-primary" @click="reschedule(ev)">Ждать до этой даты</button>
        <button class="btn" @click="editing = null">Отмена</button>
      </div>
      <div v-else class="row">
        <button class="btn" @click="editing = ev.id; newDate = ''">Клиент обещал позже</button>
        <button class="btn" @click="drop(ev)">Больше не ждать</button>
      </div>
    </article>
  </section>
</template>

<style scoped>
.missed { background: var(--risk-wash); border: 1px solid #f1c9c4; border-radius: var(--radius-l); padding: 16px; display: grid; gap: 10px; }
h2 { font-size: 17px; color: var(--risk); }
.item p { margin: 0 0 8px; }
.row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.row input { border: 1px solid var(--line); border-radius: var(--radius-s); padding: 7px 10px; }
</style>
