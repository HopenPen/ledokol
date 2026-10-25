<script setup lang="ts">
// Список компаний. Для нового пользователя главный экран — «Нужна одна загрузка»: файл выписки → компания → прогноз.
import { ArrowRight, Building2, LogOut, Plus, Trash2 } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError, logout, type Company, type ImportResult } from '../api'
import AppLogo from '../components/AppLogo.vue'
import DeleteCompanyModal from '../components/DeleteCompanyModal.vue'
import StatementUpload from '../components/StatementUpload.vue'
import { plural } from '../format'

const companies = ref<Company[]>([])
const loading = ref(true)
const error = ref('')
const creating = ref(false)
const busy = ref(false)
const name = ref('')
const deleting = ref<Company | null>(null)
const notice = ref('')
const importResults = ref<ImportResult[]>([])
const imported = computed(() => importResults.value[0] ?? null)
const importTotal = computed(() => importResults.value.reduce((sum, item) => sum + item.rows_total, 0))
const rejected = computed(() => importResults.value.reduce((sum, item) => sum + item.quality.rows_rejected, 0))
const duplicates = computed(() => importResults.value.reduce((sum, item) => sum + item.quality.duplicates, 0))
const importWarnings = computed(() => [...new Set(importResults.value.flatMap((item) => item.quality.warnings))])
let redirectTimer: number | undefined
onBeforeUnmount(() => window.clearTimeout(redirectTimer))
const router = useRouter()

onMounted(async () => {
  try { companies.value = await api.companies() } catch (e) { error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить компании' }
  finally { loading.value = false }
})

async function create() {
  if (busy.value || !name.value.trim()) return
  busy.value = true
  error.value = ''
  try { const c = await api.createCompany(name.value.trim()); router.push(`/companies/${c.id}/operations`) }
  catch (e) { error.value = e instanceof ApiError ? e.message : 'Не удалось создать компанию' }
  finally { busy.value = false }
}

// Короткая пауза на экране «что нашли», чтобы человек увидел: сервис уже разобрал его выписку сам.
function onImported(results: ImportResult[]) {
  if (!results.length) return
  importResults.value = results
  companies.value = [...new Map([...companies.value, ...results.map((item) => item.company)].map((item) => [item.id, item])).values()]
  if (results.length === 1 && !rejected.value) {
    redirectTimer = window.setTimeout(() => router.push(`/companies/${results[0].company.id}`), 1600)
  }
}
function signOut() { logout(); router.push('/login') }
function onDeleted(id: string) {
  companies.value = companies.value.filter((company) => company.id !== id)
  deleting.value = null
  notice.value = 'Компания и все связанные с ней данные удалены'
}
</script>

<template>
  <div class="wrap">
    <header class="top">
      <AppLogo />
      <button class="btn btn-ghost btn-sm" @click="signOut"><LogOut />Выйти</button>
    </header>

    <main class="page">
      <section v-if="imported" class="card found" role="status">
        <p class="f-label">Выписка разобрана</p>
        <h1>{{ importResults.length === 1 ? imported.company.name : `Компаний в выписке: ${importResults.length}` }}</h1>
        <ul class="facts">
          <li><b class="num">{{ importTotal.toLocaleString('ru-RU') }}</b> {{ plural(importTotal, 'операция', 'операции', 'операций') }}</li>
          <li v-if="importResults.length === 1"><b class="num">{{ imported.quality.history_working_days }}</b> рабочих {{ plural(imported.quality.history_working_days, 'день', 'дня', 'дней') }} истории</li>
          <li v-if="duplicates"><b class="num">{{ duplicates }}</b> {{ plural(duplicates, 'дубль убран', 'дубля убрано', 'дублей убрано') }}</li>
        </ul>
        <p v-if="rejected" class="error" role="alert">Строк с ошибками пропущено: {{ rejected }}. Проверьте исходный файл.</p>
        <p v-for="warning in importWarnings" :key="warning" class="small muted">{{ warning }}</p>
        <p v-if="importResults.length === 1 && !rejected" class="muted">Строим прогноз…</p>
        <template v-else>
          <RouterLink v-for="item in importResults" :key="item.company.id" class="btn" :to="`/companies/${item.company.id}`">{{ item.company.name }} — перейти к прогнозу</RouterLink>
          <button class="btn btn-ghost" @click="importResults = []">К списку компаний</button>
        </template>
      </section>

      <template v-else>
        <div class="head">
          <h1>{{ companies.length ? 'Ваши компании' : 'Нужна одна загрузка' }}</h1>
          <p class="muted">{{ companies.length ? 'Выберите компанию или загрузите выписку новой.' : 'Загрузите выписку по расчётному счёту: сервис сам разложит платежи по категориям, найдёт регулярные и построит прогноз.' }}</p>
        </div>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
        <p v-if="notice" class="small" role="status">{{ notice }}</p>

        <ul v-if="companies.length" class="list">
          <li v-for="c in companies" :key="c.id" class="company-row">
            <RouterLink :to="`/companies/${c.id}`" class="card company">
              <Building2 class="c-ico" aria-hidden="true" />
              <span class="c-main"><b>{{ c.name }}</b><span class="tiny">{{ c.industry || 'Отрасль не указана' }}</span></span>
              <ArrowRight class="c-go" aria-hidden="true" />
            </RouterLink>
            <button class="btn btn-ghost btn-icon btn-danger" :aria-label="`Удалить компанию «${c.name}»`" title="Удалить компанию" @click="deleting = c"><Trash2 /></button>
          </li>
        </ul>

        <StatementUpload variant="zone" @imported="onImported" />

        <div class="manual">
          <button v-if="!creating" class="btn btn-ghost" @click="creating = true"><Plus />Нет выписки? Создать компанию и вводить платежи вручную</button>
          <form v-else class="card create" @submit.prevent="create">
            <label class="field">Название компании <input v-model="name" maxlength="200" required autofocus /></label>
            <div class="row">
              <button type="button" class="btn" @click="creating = false">Отмена</button>
              <button class="btn btn-primary" :disabled="busy || !name.trim()">{{ busy ? 'Создаём…' : 'Создать' }}</button>
            </div>
          </form>
        </div>
        <p v-if="loading" class="tiny">Загружаем…</p>
      </template>
    </main>
    <DeleteCompanyModal v-if="deleting" :company="deleting" @close="deleting = null" @deleted="onDeleted" />
  </div>
</template>

<style scoped>
.top { max-width: 880px; margin: 0 auto; padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; }
.page { max-width: 880px; margin: 0 auto; padding: 24px 24px 64px; display: grid; gap: 20px; }
.head { display: grid; gap: 8px; }
.head h1 { font-size: 32px; }
.head p { max-width: 60ch; }
.list { list-style: none; padding: 0; margin: 0; display: grid; gap: 8px; }
.company-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; align-items: center; }
.company { display: flex; align-items: center; gap: 16px; padding: 16px 20px; text-decoration: none; color: inherit; transition: border-color 150ms; }
.company:hover { border-color: var(--brand); }
.c-ico { width: 22px; height: 22px; color: var(--brand); flex: none; }
.c-main { flex: 1; min-width: 0; display: grid; overflow-wrap: anywhere; }
.c-go { width: 18px; height: 18px; color: var(--ink-3); }
.manual { display: grid; justify-items: start; }
.create { width: min(420px, 100%); }
.row { display: flex; gap: 8px; justify-content: flex-end; }
.found { display: grid; gap: 12px; padding: 32px; }
.f-label { color: var(--brand); font-weight: 600; font-size: 14px; }
.facts { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 8px 24px; font-size: 18px; }
.facts b { font-size: 28px; letter-spacing: -0.02em; }
@media (max-width: 640px) { .top, .page { padding-left: 16px; padding-right: 16px; } .head h1 { font-size: 26px; } }
</style>
