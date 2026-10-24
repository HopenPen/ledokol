<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'
import AuthLayout from '../components/AuthLayout.vue'

const route = useRoute()
const resendOnly = computed(() => route.query.resend === '1')
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

async function submit(resend = false) {
  if (busy.value) return
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
    <template v-if="sent">
      <h1>Проверьте почту</h1>
      <p class="lead">{{ message }}</p>
      <p class="hint">Адрес: {{ email }}. Откройте письмо и перейдите по ссылке подтверждения.</p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <button class="btn submit" :disabled="busy || cooldown > 0" @click="submit(true)">
        {{ busy ? 'Отправляем…' : cooldown ? `Повторить через ${cooldown} с` : 'Отправить письмо ещё раз' }}
      </button>
      <p class="foot"><RouterLink to="/login">Перейти ко входу</RouterLink></p>
    </template>
    <form v-else @submit.prevent="submit()">
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
      <button class="btn btn-primary submit" :disabled="busy">
        {{ busy ? 'Отправляем…' : resendOnly ? 'Отправить ссылку' : 'Зарегистрироваться' }}
      </button>
      <p v-if="!resendOnly" class="hint">После регистрации подтвердите email по ссылке из письма.</p>
      <p class="foot">Уже есть аккаунт? <RouterLink to="/login">Войти</RouterLink></p>
    </form>
  </AuthLayout>
</template>
