<script setup lang="ts">
// Ассистент «спросить о своих деньгах» сохраняется (требование продукта). Он видит только обезличенную
// сводку прогноза; назначения платежей, названия контрагентов и вложения к нему не попадают.
import { Send, X } from 'lucide-vue-next'
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, ApiError } from '../api'

const props = defineProps<{ companyId: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()
const question = ref('')
const history = ref<{ q: string; a: string; by: string }[]>([])
const busy = ref(false)
const log = ref<HTMLDivElement | null>(null)
const input = ref<HTMLInputElement | null>(null)
const CHIPS = ['Хватит ли денег до зарплаты?', 'Почему может не хватить денег?', 'Что будет, если клиент заплатит позже?']

async function send(q = question.value) {
  if (!q.trim() || busy.value) return
  busy.value = true
  const index = history.value.length
  history.value.push({ q: q.trim(), a: '', by: '' })
  question.value = ''
  await nextTick()
  log.value?.scrollTo({ top: log.value.scrollHeight })
  try {
    const r = await api.ask(props.companyId, q.trim())
    Object.assign(history.value[index], { a: r.answer, by: r.generated_by })
  } catch (e) {
    Object.assign(history.value[index], { a: e instanceof ApiError ? e.message : 'Не получилось ответить', by: 'error' })
  } finally {
    busy.value = false
    await nextTick()
    log.value?.scrollTo({ top: log.value.scrollHeight })
  }
}
const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') emit('close') }
onMounted(() => { window.addEventListener('keydown', onKey); input.value?.focus() })
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <aside class="panel" role="dialog" aria-modal="false" aria-labelledby="ask-title">
    <header>
      <div><h2 id="ask-title">Спросить о своих деньгах</h2><p class="tiny">Ответ строится по вашему прогнозу</p></div>
      <button class="btn btn-ghost btn-icon" aria-label="Закрыть" @click="emit('close')"><X /></button>
    </header>
    <div ref="log" class="log">
      <div v-if="!history.length" class="chips">
        <button v-for="c in CHIPS" :key="c" class="btn btn-sm chip-btn" @click="send(c)">{{ c }}</button>
      </div>
      <div v-for="(m, i) in history" :key="i" class="msg">
        <p class="q">{{ m.q }}</p>
        <p v-if="m.a" class="a" :class="{ err: m.by === 'error' }">{{ m.a }}</p>
        <p v-if="m.a && m.by !== 'error'" class="tiny">{{ m.by === 'template' ? 'Ответ по шаблону, цифры из прогноза' : 'Ответ сгенерирован моделью, цифры из прогноза' }}</p>
      </div>
      <p v-if="busy" class="tiny">Думаем…</p>
    </div>
    <form @submit.prevent="send()">
      <input ref="input" v-model="question" class="input" maxlength="500" placeholder="Например: хватит ли денег до 20 ноября?" aria-label="Вопрос" />
      <button class="btn btn-primary btn-icon" :disabled="busy || !question.trim()" aria-label="Отправить"><Send /></button>
    </form>
    <p class="tiny privacy">Ассистент видит только суммы и даты прогноза. Назначения платежей, контрагенты и ваши файлы ему не передаются.</p>
  </aside>
</template>

<style scoped>
.panel {
  position: fixed; right: 16px; bottom: 16px; top: 80px; width: min(420px, calc(100% - 32px)); z-index: 40;
  display: flex; flex-direction: column; gap: 12px; padding: 20px; background: var(--surface);
  border: 1px solid var(--line); border-radius: 14px; box-shadow: var(--shadow-pop);
}
header { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
h2 { font-size: 18px; }
.log { flex: 1; overflow-y: auto; display: grid; gap: 16px; align-content: start; }
.chips { display: grid; gap: 6px; justify-items: start; }
.chip-btn { white-space: normal; text-align: left; }
.msg { display: grid; gap: 4px; }
.q { justify-self: end; background: var(--brand-soft); color: var(--ink); padding: 8px 12px; border-radius: 12px 12px 4px 12px; max-width: 85%; }
.a { background: var(--bg); padding: 10px 12px; border-radius: 12px 12px 12px 4px; }
.a.err { color: var(--risk); }
form { display: flex; gap: 8px; }
form .input { min-height: 40px; }
.privacy { border-top: 1px solid var(--line); padding-top: 8px; }
@media (max-width: 640px) { .panel { top: 16px; } }
</style>
