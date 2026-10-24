<script setup lang="ts">
// Главный экран: ответ одной фразой → график → предупреждения → ближайшие события.
import { computed, inject, ref, type Ref } from 'vue'
import { useRoute } from 'vue-router'
import type { Dashboard } from '../api'
import AddEventModal from '../components/AddEventModal.vue'
import AlertCard from '../components/AlertCard.vue'
import BalanceChart from '../components/BalanceChart.vue'
import { chance, humanDate, rub, SOURCE_LABEL } from '../format'

const dashboard = inject<Ref<Dashboard | null>>('dashboard')!
const reload = inject<() => Promise<void>>('reload')!
const route = useRoute()
const modal = ref<{ preset?: string } | null>(null)
const toast = ref('')

const f = computed(() => dashboard.value?.forecast)
const tone = computed(() => !f.value?.alerts.length ? 'ok' : f.value.alerts[0].probability >= 0.5 ? 'risk' : 'warn')

async function onSaved() {
  modal.value = null
  await reload()
  toast.value = 'Событие добавлено — прогноз пересчитан'
  setTimeout(() => (toast.value = ''), 4000)
}
</script>

<template>
  <p v-if="!dashboard">Считаем прогноз…</p>
  <div v-else-if="f" class="layout">
    <section class="hero" :class="tone">
      <h2 class="answer">{{ f.headline }}</h2>
      <p class="sub num">Сейчас на счёте {{ rub(f.last_balance) }} · данные выписки на {{ humanDate(f.as_of) }}</p>
      <p v-if="f.low_history" class="note">Истории пока мало — прогноз приблизительный.</p>
      <p v-for="w in f.warnings" :key="w" class="note">{{ w }}</p>
    </section>

    <section class="card chart-card">
      <BalanceChart :history="dashboard.history" :points="f.points" :threshold="f.threshold" />
    </section>

    <section class="alerts">
      <h2>Предупреждения</h2>
      <p v-if="!f.alerts.length" class="ok-plate">Нехватки денег не видно на ближайшие {{ f.points.length }} рабочих дней.</p>
      <AlertCard v-for="a in f.alerts" :key="a.start" :alert="a" @move-payment="(t) => (modal = { preset: t })" />
    </section>

    <section class="card events">
      <header class="events-head">
        <h2>Ближайшие события</h2>
        <button class="btn btn-primary" @click="modal = {}">Добавить событие</button>
      </header>
      <p v-if="toast" class="toast" role="status">{{ toast }}</p>
      <ul>
        <li v-for="e in f.events.slice(0, 25)" :key="e.date + e.title + e.amount">
          <span class="date">{{ humanDate(e.date) }}</span>
          <span class="title">{{ e.title }} <span class="badge" :class="`badge-${e.source}`">{{ SOURCE_LABEL[e.source] }}</span></span>
          <span class="amount num" :class="e.direction">{{ e.direction === 'in' ? '+' : '−' }}{{ rub(e.amount) }}</span>
          <span class="chance">{{ chance(e.probability) }}</span>
        </li>
      </ul>
    </section>

    <AddEventModal v-if="modal" :company-id="route.params.id as string" :min-date="f.as_of"
                   :preset-title="modal.preset" @close="modal = null" @saved="onSaved" />
  </div>
</template>

<style scoped>
.layout { display: grid; gap: 20px; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); }
.hero, .chart-card { grid-column: 1; }
.alerts { grid-column: 2; grid-row: 1 / span 3; display: grid; gap: 12px; align-content: start; }
.events { grid-column: 1; }
/* Единственный «громкий» элемент экрана — ответ. Крупный, плотный, с цветной чертой слева по уровню риска. */
.hero { padding: 8px 0 8px 20px; border-left: 6px solid var(--green); }
.hero.warn { border-left-color: var(--warn); }
.hero.risk { border-left-color: var(--risk); }
.answer { font-size: clamp(26px, 3.6vw, 40px); line-height: 1.12; font-weight: 700; max-width: 22ch; }
.sub { color: var(--ink-2); margin: 10px 0 0; }
.note { color: var(--warn); margin: 6px 0 0; font-size: 14px; }
.alerts h2, .events h2 { font-size: 18px; }
.ok-plate { background: var(--green-wash); color: var(--green); padding: 14px; border-radius: var(--radius-l); margin: 0; }
.events-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 8px; }
.events ul { list-style: none; padding: 0; margin: 0; }
.events li { display: grid; grid-template-columns: 96px 1fr auto; gap: 4px 12px; padding: 10px 0; border-top: 1px solid var(--line); }
.date { color: var(--ink-2); }
.amount.in { color: var(--green); }
.chance { grid-column: 2 / 4; color: var(--muted); font-size: 13px; }
.chance:empty { display: none; }
.toast { color: var(--green); }
@media (max-width: 860px) {
  .layout { grid-template-columns: 1fr; }
  .alerts { grid-column: 1; grid-row: auto; }
}
</style>
