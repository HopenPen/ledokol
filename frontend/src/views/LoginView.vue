<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError } from '../api'

const login = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)
const router = useRouter()

async function submit() {
  error.value = ''
  busy.value = true
  try {
    await api.login(login.value, password.value)
    router.push('/companies')
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Сервер недоступен'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="login">
    <form class="card" @submit.prevent="submit">
      <h1>Деньги вперёд</h1>
      <p class="lead">Прогноз остатка на счёте и предупреждения, если денег может не хватить.</p>
      <label class="field">Логин <input v-model="login" autocomplete="username" required /></label>
      <label class="field">Пароль <input v-model="password" type="password" autocomplete="current-password" required /></label>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <button class="btn btn-primary" :disabled="busy">{{ busy ? 'Входим…' : 'Войти' }}</button>
    </form>
  </main>
</template>

<style scoped>
.login { min-height: 100vh; display: grid; place-items: center; padding: 16px; }
form { width: min(380px, 100%); }
h1 { font-size: 28px; margin-bottom: 4px; }
.lead { color: var(--ink-2); margin: 0 0 20px; }
button { width: 100%; }
</style>
