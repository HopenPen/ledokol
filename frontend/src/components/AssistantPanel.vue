<script setup lang="ts">
import { ref } from 'vue'
import { api, ApiError } from '../api'

const props = defineProps<{ companyId: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()
const question = ref('')
const history = ref<{ q: string; a: string; by: string }[]>([])
const busy = ref(false)
const CHIPS = ['Хватит ли денег до зарплаты?', 'Почему может не хватить денег?', 'Что будет, если клиент заплатит позже?']

async function send(q = question.value) {
  if (!q.trim()) return
  busy.value = true
  try {
    const r = await api.ask(props.companyId, q)
    history.value.push({ q, a: r.answer, by: r.generated_by })
    question.value = ''
  } catch (e) {
    history.value.push({ q, a: e instanceof ApiError ? e.message : 'Не получилось ответить', by: 'error' })
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <aside class="panel card" aria-label="Ассистент">
    <header><h2>Спросить о своих деньгах</h2><button class="btn" @click="emit('close')">Закрыть</button></header>
    <div class="chips"><button v-for="c in CHIPS" :key="c" class="btn chip" @click="send(c)">{{ c }}</button></div>
    <div class="log">
      <div v-for="(m, i) in history" :key="i">
        <p class="q">{{ m.q }}</p>
        <p class="a">{{ m.a }}</p>
        <p class="by">{{ m.by === 'template' ? 'Ответ составлен по шаблону' : m.by === 'error' ? '' : 'Ответ сгенерирован моделью, цифры — из прогноза' }}</p>
      </div>
    </div>
    <form @submit.prevent="send()">
      <input v-model="question" maxlength="500" placeholder="Например: хватит ли денег до 20 ноября?" aria-label="Вопрос" />
      <button class="btn btn-primary" :disabled="busy">Отправить</button>
    </form>
  </aside>
</template>

<style scoped>
.panel { position: fixed; right: 16px; bottom: 16px; top: 16px; width: min(420px, calc(100% - 32px)); display: flex; flex-direction: column; gap: 12px; z-index: 20; }
header { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
h2 { font-size: 18px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { font-size: 13px; }
.log { flex: 1; overflow-y: auto; }
.q { font-weight: 500; margin: 12px 0 4px; }
.a { margin: 0; }
.by { color: var(--muted); font-size: 12px; margin: 4px 0 0; }
form { display: flex; gap: 8px; }
form input { flex: 1; border: 1px solid var(--line); border-radius: var(--radius-s); padding: 8px 10px; }
</style>
