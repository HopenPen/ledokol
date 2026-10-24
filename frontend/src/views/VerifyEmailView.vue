<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import AuthLayout from '../components/AuthLayout.vue'

const route = useRoute()
const router = useRouter()
const token = new URLSearchParams(route.hash.slice(1)).get('token') ?? ''
const busy = ref(false)
const confirmed = ref(false)
const error = ref(token ? '' : 'В ссылке нет кода подтверждения. Запросите новое письмо.')
onMounted(() => { if (route.hash) router.replace({ path: route.path, hash: '' }) })

async function confirm() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try { await api.verifyEmail(token); confirmed.value = true }
  catch (e) { error.value = e instanceof Error ? e.message : 'Сервер недоступен' }
  finally { busy.value = false }
}
</script>

<template>
  <AuthLayout>
    <h1>{{ confirmed ? 'Email подтверждён' : 'Подтвердите email' }}</h1>
    <p class="lead">{{ confirmed ? 'Аккаунт готов. Войдите с вашим email и паролем.' : 'Остался один шаг, чтобы начать работу с платежами.' }}</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <button v-if="token && !confirmed" class="btn btn-primary submit" :disabled="busy" @click="confirm">
      {{ busy ? 'Подтверждаем…' : 'Подтвердить email' }}
    </button>
    <p class="foot"><RouterLink :to="confirmed ? '/login' : '/register?resend=1'">
      {{ confirmed ? 'Войти в приложение' : 'Запросить новое письмо' }}
    </RouterLink></p>
  </AuthLayout>
</template>
