<script setup lang="ts">
import { ref } from 'vue'
import type { Alert } from '../api'
import { humanDate, rub, SOURCE_LABEL } from '../format'

const props = defineProps<{ alert: Alert }>()
const emit = defineEmits<{ (e: 'move-payment', title: string): void }>()
const toast = ref('')

const severity = props.alert.probability >= 0.8 ? 'high' : props.alert.probability >= 0.5 ? 'mid' : 'low'

async function act(action: string) {
  if (action.startsWith('Перенести')) emit('move-payment', action)
  else if (action.startsWith('Напомнить')) {
    await navigator.clipboard?.writeText('Добрый день! Напоминаем об оплате счёта. Спасибо!')
    toast.value = 'Текст напоминания скопирован'
  } else toast.value = `Заявка на овердрафт на ${rub(props.alert.shortfall * 1.1)} отправлена (демо)`
}
</script>

<template>
  <article class="alert" :class="severity">
    <h3>{{ humanDate(alert.start) }} не хватит {{ rub(alert.shortfall) }}</h3>
    <p class="level">{{ alert.level }}<template v-if="alert.worst_case">, в плохом сценарии</template></p>
    <p v-if="alert.causes.length" class="why">
      Почему:
      <span v-for="c in alert.causes" :key="c.title + c.date" class="cause">
        {{ c.title }} — {{ rub(c.amount) }} <span class="badge">{{ SOURCE_LABEL[c.source] }}</span>
      </span>
    </p>
    <div class="actions">
      <button v-for="a in alert.actions" :key="a" class="btn" @click="act(a)">{{ a }}</button>
    </div>
    <p v-if="toast" class="toast" role="status">{{ toast }}</p>
  </article>
</template>

<style scoped>
.alert { border-radius: var(--radius-l); padding: 16px; border: 1px solid var(--line); background: var(--surface); border-left: 4px solid var(--warn); }
.alert.high { border-left-color: var(--risk); background: var(--risk-wash); }
.alert.low { border-left-color: var(--muted); }
h3 { font-size: 17px; }
.level { margin: 2px 0 8px; color: var(--ink-2); }
.why { display: grid; gap: 2px; margin: 0 0 12px; font-size: 14px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; }
.actions .btn { font-size: 14px; text-align: left; }
.toast { margin: 8px 0 0; color: var(--green); font-size: 14px; }
</style>
