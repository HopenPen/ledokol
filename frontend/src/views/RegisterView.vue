<script setup lang="ts">
// Режим регистрации берём у API: по умолчанию после создания аккаунта сразу входим.
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError, type RegistrationInfo } from '../api'
import AuthLayout from '../components/AuthLayout.vue'

const email = ref('')
const password = ref('')
const repeat = ref('')
const error = ref('')
const message = ref('')
const busy = ref(false)
const loading = ref(true)
const registration = ref<RegistrationInfo | null>(null)
const verificationRequired = computed(() => registration.value?.email_delivery !== 'disabled')
const route = useRoute()
const resendOnly = computed(() => verificationRequired.value && route.query.resend === '1')
const router = useRouter()
const cooldown = ref(0)
const timer = setInterval(() => { if (cooldown.value > 0) --cooldown.value }, 1000)
onUnmounted(() => clearInterval(timer))

async function loadRegistration() {
  loading.value = true
  error.value = ''
  try { registration.value = await api.registrationInfo() }
  catch { error.value = 'Не удалось получить настройки регистрации. Попробуйте ещё раз.' }
  finally { loading.value = false }
}
onMounted(loadRegistration)

async function submit(resend = false) {
  if (busy.value || !registration.value || registration.value.email_delivery === 'unavailable') return
  error.value = ''
  const sendingLink = resend || resendOnly.value
  if (!sendingLink && password.value.length < 8) { error.value = 'Пароль должен быть не короче 8 символов'; return }
  if (!sendingLink && password.value !== repeat.value) { error.value = 'Пароли не совпадают'; return }
  busy.value = true
  try {
    const result = sendingLink
      ? await api.resendVerification(email.value.trim())
      : await api.register(email.value.trim(), password.value)
    message.value = result.message
    cooldown.value = 60
    if (!verificationRequired.value) {
      try { await api.login(email.value.trim(), password.value); await router.push('/companies') }
      catch (e) { error.value = e instanceof ApiError ? e.message : 'Аккаунт сохранён, но вход не удался. Попробуйте войти ещё раз.' }
    }
    password.value = repeat.value = ''
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Сервер недоступен. Попробуйте ещё раз через минуту'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <AuthLayout>
    <p v-if="loading" class="lead" role="status">Загружаем настройки регистрации…</p>
    <div v-else-if="message" class="done">
      <h1>{{ verificationRequired ? 'Проверьте почту' : 'Можно войти' }}</h1>
      <p class="lead">{{ message }}</p>
      <p v-if="error" class="error form-error" role="alert">{{ error }}</p>
      <p v-if="verificationRequired && registration?.local_mailbox_url" class="foot-link">
        <a :href="registration.local_mailbox_url" target="_blank" rel="noopener noreferrer">Открыть тестовый почтовый ящик</a>
      </p>
      <button v-if="verificationRequired" class="btn submit" :disabled="busy || cooldown > 0" @click="submit(true)">
        {{ busy ? 'Отправляем…' : cooldown ? `Повторить через ${cooldown} с` : 'Отправить письмо ещё раз' }}
      </button>
      <RouterLink class="btn btn-primary submit" to="/login">Перейти ко входу</RouterLink>
    </div>
    <form v-else-if="registration" @submit.prevent="submit()">
      <h1>{{ resendOnly ? 'Подтверждение email' : 'Регистрация' }}</h1>
      <p class="lead">{{ resendOnly ? 'Отправим новую ссылку подтверждения.' : 'Загрузите выписку и через минуту увидите прогноз остатка.' }}</p>
      <label class="field">Email
        <input v-model="email" type="email" autocomplete="email" maxlength="254" required autofocus />
      </label>
      <label v-if="!resendOnly" class="field">Пароль
        <input v-model="password" type="password" autocomplete="new-password" minlength="8" maxlength="256" required />
        <span class="hint">Не короче 8 символов</span>
      </label>
      <label v-if="!resendOnly" class="field">Пароль ещё раз
        <input v-model="repeat" type="password" autocomplete="new-password" minlength="8" maxlength="256" required />
      </label>
      <p v-if="error" class="error form-error" role="alert">{{ error }}</p>
      <p v-if="registration.email_delivery === 'unavailable'" class="error" role="alert">Отправка писем подтверждения пока не настроена.</p>
      <button class="btn btn-primary submit" :disabled="busy || registration.email_delivery === 'unavailable' || !email || (!resendOnly && (!password || !repeat))">
        {{ busy ? 'Отправляем…' : resendOnly ? 'Отправить ссылку' : 'Зарегистрироваться' }}
      </button>
      <p class="foot-link">Уже есть аккаунт? <RouterLink to="/login">Войти</RouterLink></p>
    </form>
    <template v-else>
      <p class="error" role="alert">{{ error }}</p>
      <button class="btn submit" @click="loadRegistration">Повторить</button>
    </template>
  </AuthLayout>
</template>

<style scoped>
.form-error { margin: -4px 0 16px; }
</style>
