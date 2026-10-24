<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError } from '../api'
import AuthLayout from '../components/AuthLayout.vue'

const login = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)
const needsVerification = ref(false)
const router = useRouter()

async function submit() {
  if (busy.value) return
  error.value = ''
  needsVerification.value = false
  busy.value = true
  try {
    await api.login(login.value, password.value)
    router.push('/companies')
  } catch (e) {
    needsVerification.value = e instanceof ApiError && e.status === 403
    error.value = e instanceof ApiError ? e.message : 'Сервер недоступен'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <AuthLayout>
    <form @submit.prevent="submit">
      <h1>Вход в систему</h1>
      <p class="lead">Прогноз остатка на счёте и предупреждения, если денег может не хватить.</p>
      <label class="field">Email или логин <input v-model="login" autocomplete="username" maxlength="254" required /></label>
      <label class="field">Пароль <input v-model="password" type="password" autocomplete="current-password" required /></label>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <p v-if="needsVerification"><RouterLink to="/register?resend=1">Отправить письмо ещё раз</RouterLink></p>
      <button class="btn btn-primary submit" :disabled="busy">{{ busy ? 'Входим…' : 'Войти' }}</button>
      <p class="foot">Нет аккаунта? <RouterLink to="/register">Зарегистрироваться</RouterLink></p>
    </form>
  </AuthLayout>
</template>
