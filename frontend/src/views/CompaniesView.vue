<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, type Company } from '../api'
import StatementUpload from '../components/StatementUpload.vue'

const companies = ref<Company[]>([])
const loading = ref(true)
const error = ref('')
const creating = ref(false)
const busy = ref(false)
const name = ref('')
const router = useRouter()

onMounted(async () => {
  try { companies.value = await api.companies() } catch (e) { error.value = (e as Error).message } finally { loading.value = false }
})

async function create() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const company = await api.createCompany(name.value)
    router.push(`/companies/${company.id}/operations`)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="page">
    <header class="head">
      <h1>Мои компании</h1>
      <button class="btn btn-primary" @click="creating = !creating">Добавить компанию</button>
    </header>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <form v-if="creating" class="card create" @submit.prevent="create">
      <label class="field">Название компании <input v-model="name" maxlength="200" required autofocus /></label>
      <button class="btn btn-primary" :disabled="busy">{{ busy ? 'Создаём…' : 'Создать компанию' }}</button>
    </form>
    <StatementUpload @imported="(results) => router.push(`/companies/${results[0].company.id}`)" />
    <p v-if="loading">Загружаем…</p>
    <section v-else-if="!companies.length" class="card empty">
      <h2>Пока нет ни одной компании</h2>
      <p>Создайте компанию для ручного ввода платежей или загрузите банковскую выписку — компания появится автоматически.</p>
    </section>
    <ul v-else class="grid">
      <li v-for="c in companies" :key="c.id">
        <RouterLink :to="`/companies/${c.id}`" class="card company">
          <strong>{{ c.name }}</strong>
          <span class="muted">{{ c.industry || 'Отрасль не указана' }}</span>
        </RouterLink>
      </li>
    </ul>
  </main>
</template>

<style scoped>
.page { max-width: 960px; margin: 0 auto; padding: 32px 16px; }
.head { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 24px; }
.grid { list-style: none; padding: 0; display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); }
.company { display: grid; gap: 4px; text-decoration: none; color: inherit; }
.company:hover { border-color: var(--green); }
.muted { color: var(--muted); font-size: 14px; }
.empty p { color: var(--ink-2); }
.create { margin-bottom: 20px; max-width: 420px; }
</style>
