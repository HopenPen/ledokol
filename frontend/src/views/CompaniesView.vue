<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError, type Company } from '../api'

const companies = ref<Company[]>([])
const loading = ref(true)
const error = ref('')
const uploading = ref(false)
const router = useRouter()

onMounted(async () => {
  try { companies.value = await api.companies() } catch (e) { error.value = (e as Error).message } finally { loading.value = false }
})

async function onFile(ev: Event) {
  const file = (ev.target as HTMLInputElement).files?.[0]
  if (!file) return
  uploading.value = true
  error.value = ''
  try {
    const res = await api.importStatement(file)
    router.push(`/companies/${res[0].company.id}`)   // загрузил — сразу видишь прогноз
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Не удалось загрузить файл'
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <main class="page">
    <header class="head">
      <h1>Мои компании</h1>
      <label class="btn btn-primary">
        {{ uploading ? 'Загружаем…' : 'Загрузить выписку' }}
        <input type="file" accept=".csv" hidden @change="onFile" />
      </label>
    </header>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="loading">Загружаем…</p>
    <section v-else-if="!companies.length" class="card empty">
      <h2>Пока нет ни одной компании</h2>
      <p>Загрузите выписку из банка в формате CSV — прогноз появится сразу, ничего настраивать не нужно.</p>
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
</style>
