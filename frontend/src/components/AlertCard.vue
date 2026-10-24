<script setup lang="ts">
// Одна карточка = один разрыв: когда, сколько, насколько вероятно, из-за чего и что сделать.
// Действия честные: готовим текст письма или подсказываем сумму. Ничего не «отправляем» от имени банка.
import { ChevronDown, Copy, TriangleAlert } from 'lucide-vue-next'
import { computed, inject, ref } from 'vue'
import type { Alert } from '../api'
import { chanceWords, humanDate, percent, rub, signed, SOURCE_LABEL } from '../format'

const props = withDefaults(defineProps<{ alert: Alert; startOpen?: boolean }>(), { startOpen: true })
const expanded = ref(props.startOpen)
const toast = inject<(t: string) => void>('toast', () => {})
const open = ref<string | null>(null)

const severity = computed(() => (props.alert.worst_case ? 'low' : props.alert.probability >= 0.8 ? 'high' : 'mid'))
const title = computed(() => `${humanDate(props.alert.start)} может не хватить ${rub(props.alert.shortfall)}`)
const actions = computed(() => props.alert.actions.map((text) => {
  if (text.startsWith('Перенести')) {
    const m = text.match(/«(.+?)».*?на (\d+ \S+)/)
    return { key: 'move', label: 'Перенести платёж', text,
             letter: `Добрый день! Просим согласовать перенос оплаты${m ? ` «${m[1]}»` : ''}${m ? ` на ${m[2]}` : ''}. Спасибо!` }
  }
  if (text.startsWith('Напомнить')) {
    const m = text.match(/«(.+?)»/)
    return { key: 'remind', label: 'Напомнить клиенту', text,
             letter: `Добрый день! Напоминаем об оплате${m ? ` (${m[1]})` : ' счёта'}. Будем благодарны за оплату в срок. Спасибо!` }
  }
  return { key: 'finance', label: 'Рассмотреть овердрафт', text, letter: '' }
}))

async function copy(letter: string) {
  try { await navigator.clipboard.writeText(letter); toast('Текст скопирован') } catch { toast('Не удалось скопировать: выделите текст вручную') }
}
</script>

<template>
  <article class="alert" :class="severity">
    <header>
      <TriangleAlert class="ico" aria-hidden="true" />
      <div class="h-main">
        <h3>{{ title }}</h3>
        <p class="meta">
          <span class="chip" :class="severity === 'high' ? 'chip-risk' : 'chip-warn'">{{ chanceWords(alert.probability) }} · {{ percent(alert.probability) }}</span>
          <span v-if="alert.worst_case" class="tiny">только в плохом сценарии</span>
          <span v-if="alert.end !== alert.start" class="tiny">до {{ humanDate(alert.end) }}</span>
        </p>
      </div>
      <button class="btn btn-ghost btn-icon toggle" :aria-expanded="expanded" :aria-label="expanded ? 'Свернуть' : 'Подробнее'"
              @click="expanded = !expanded"><ChevronDown :class="{ flip: expanded }" /></button>
    </header>

    <template v-if="expanded">
    <div v-if="alert.causes.length" class="why">
      <p class="label">Главные платежи в эти дни</p>
      <ul>
        <li v-for="c in alert.causes" :key="c.title + c.date">
          <div class="c-main"><span class="c-title">{{ c.title }}</span><span class="amount">{{ signed(c.amount, c.direction) }}</span></div>
          <div class="c-meta"><span class="src" :class="`src-${c.source}`">{{ SOURCE_LABEL[c.source] ?? c.source }}</span><span class="tiny">{{ humanDate(c.date) }}</span></div>
        </li>
      </ul>
    </div>

    <div class="actions">
      <p class="label">Что можно сделать</p>
      <div class="btns">
        <button v-for="a in actions" :key="a.key" class="btn btn-sm" :aria-expanded="open === a.key"
                @click="open = open === a.key ? null : a.key">{{ a.label }}</button>
      </div>
      <template v-for="a in actions" :key="'p' + a.key">
        <div v-if="open === a.key" class="pane">
          <p class="small">{{ a.text }}</p>
          <template v-if="a.letter">
            <p class="letter">{{ a.letter }}</p>
            <button class="btn btn-sm" @click="copy(a.letter)"><Copy />Скопировать текст</button>
          </template>
          <p v-else class="small muted">Сумма с запасом 10%: <b class="num">{{ rub(alert.shortfall * 1.1) }}</b>. Заявку подают в приложении вашего банка.</p>
        </div>
      </template>
    </div>
    </template>
  </article>
</template>

<style scoped>
.alert { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 20px; display: grid; gap: 16px; }
.alert.high { border-color: var(--risk-line); box-shadow: inset 4px 0 0 var(--risk); }
.alert.mid { border-color: var(--warn-line); box-shadow: inset 4px 0 0 var(--warn); }
.alert.low { box-shadow: inset 4px 0 0 var(--line-strong); }
header { display: flex; gap: 12px; align-items: flex-start; }
.ico { width: 22px; height: 22px; flex: none; margin-top: 2px; color: var(--warn); }
.high .ico { color: var(--risk); }
h3 { font-size: 18px; }
.meta { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 6px; }
.label { font-size: 13px; font-weight: 600; color: var(--ink-2); margin-bottom: 6px; }
.why ul { list-style: none; padding: 0; margin: 0; }
.why li { padding: 8px 0; border-top: 1px solid var(--line); display: grid; gap: 4px; }
.c-main { display: flex; justify-content: space-between; gap: 12px; }
.c-main .amount { white-space: nowrap; font-weight: 600; }
.h-main { flex: 1; min-width: 0; }
.toggle svg { transition: transform 150ms; }
.toggle .flip { transform: rotate(180deg); }
.c-title { font-weight: 550; }
.c-meta { display: flex; gap: 8px; align-items: center; }
.btns { display: flex; flex-wrap: wrap; gap: 8px; }
.pane { margin-top: 12px; padding: 12px; background: var(--bg); border-radius: var(--radius-s); display: grid; gap: 8px; justify-items: start; }
.letter { font-size: 14px; padding: 10px 12px; background: var(--surface); border: 1px dashed var(--line-strong); border-radius: var(--radius-s); width: 100%; }
</style>
