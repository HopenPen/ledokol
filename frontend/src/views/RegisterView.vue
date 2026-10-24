<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, type RegistrationInfo } from '../api'
import AuthLayout from '../components/AuthLayout.vue'

const route = useRoute()
const registration = ref<RegistrationInfo | null>(null)
const loading = ref(true)
const verificationRequired = computed(() => registration.value?.email_delivery !== 'disabled')
const resendOnly = computed(() => verificationRequired.value && route.query.resend === '1')
const email = ref('')
const password = ref('')
const repeat = ref('')
const error = ref('')
const message = ref('')
const sent = ref(false)
const busy = ref(false)
const cooldown = ref(0)
const timer = setInterval(() => { if (cooldown.value > 0) cooldown.value-- }, 1000)
onUnmounted(() => clearInterval(timer))

async function loadRegistrationInfo() {
  loading.value = true
  error.value = ''
  try { registration.value = await api.registrationInfo() }
  catch { error.value = 'Не удалось получить настройки регистрации. Попробуйте ещё раз.' }
  finally { loading.value = false }
}
onMounted(loadRegistrationInfo)

async function submit(resend = false) {
  if (busy.value || !registration.value || registration.value.email_delivery === 'unavailable') return
  error.value = ''
  if (!resend && !resendOnly.value && password.value !== repeat.value) {
    error.value = 'Пароли не совпадают'
    return
  }
  busy.value = true
  try {
    const result = resend || resendOnly.value
      ? await api.resendVerification(email.value.trim())
      : await api.register(email.value.trim(), password.value)
    message.value = result.message
    sent.value = true
    password.value = repeat.value = ''
    cooldown.value = 60
  } catch (e) { error.value = e instanceof Error ? e.message : 'Сервер недоступен' }
  finally { busy.value = false }
}
</script>

<template>
  <AuthLayout>
    <p v-if="loading" class="lead" role="status">Загружаем настройки регистрации…</p>
    <template v-else-if="sent">
      <h1>{{ verificationRequired ? 'Проверьте почту' : 'Можно войти' }}</h1>
      <p class="lead">{{ message }}</p>
      <p v-if="verificationRequired" class="hint">Адрес: {{ email }}. Откройте письмо и перейдите по ссылке подтверждения.</p>
      <p v-if="registration?.local_mailbox_url" class="hint">
        <a :href="registration.local_mailbox_url" target="_blank" rel="noopener noreferrer">Открыть тестовый почтовый ящик</a>
      </p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <button v-if="verificationRequired" class="btn submit" :disabled="busy || cooldown > 0" @click="submit(true)">
        {{ busy ? 'Отправляем…' : cooldown ? `Повторить через ${cooldown} с` : 'Отправить письмо ещё раз' }}
      </button>
      <p class="foot"><RouterLink to="/login">Перейти ко входу</RouterLink></p>
    </template>
    <form v-else-if="registration" @submit.prevent="submit()">
      <h1>{{ resendOnly ? 'Подтверждение email' : 'Создать аккаунт' }}</h1>
      <p class="lead">{{ resendOnly ? 'Укажите адрес регистрации — отправим новую ссылку.' : 'Следите за платежами и планируйте остаток на счёте.' }}</p>
      <label class="field">Email
        <input v-model="email" type="email" autocomplete="email" maxlength="254" required autofocus />
      </label>
      <template v-if="!resendOnly">
        <label class="field">Пароль
          <input v-model="password" type="password" autocomplete="new-password" minlength="8" maxlength="256" required />
          <span class="hint">Не менее 8 символов</span>
        </label>
        <label class="field">Повторите пароль
          <input v-model="repeat" type="password" autocomplete="new-password" minlength="8" maxlength="256" required />
        </label>
      </template>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <p v-if="registration.email_delivery === 'unavailable'" class="error" role="alert">Отправка писем подтверждения пока не настроена.</p>
      <button class="btn btn-primary submit" :disabled="busy || registration.email_delivery === 'unavailable'">
        {{ busy ? 'Отправляем…' : resendOnly ? 'Отправить ссылку' : 'Зарегистрироваться' }}
      </button>
      <p v-if="!resendOnly" class="hint">{{ verificationRequired ? 'После регистрации подтвердите email по ссылке из письма.' : 'После регистрации можно сразу войти.' }}</p>
      <p class="foot">Уже есть аккаунт? <RouterLink to="/login">Войти</RouterLink></p>
    </form>
    <template v-else>
      <p class="error" role="alert">{{ error }}</p>
      <button class="btn submit" @click="loadRegistrationInfo">Повторить</button>
    </template>
  </AuthLayout>
</template>
