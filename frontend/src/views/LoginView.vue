<script setup lang="ts">
import { Landmark } from 'lucide-vue-next'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError, SSO_CENTRINVEST_URL } from '../api'
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
    await api.login(login.value.trim(), password.value)
    router.push('/companies')
  } catch (e) {
    needsVerification.value = e instanceof ApiError && e.status === 403
    error.value = e instanceof ApiError ? e.message : 'Сервер недоступен. Попробуйте ещё раз через минуту'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <AuthLayout>
    <form novalidate @submit.prevent="submit">
      <h1>Вход</h1>
      <p class="lead">Прогноз остатка на счёте и предупреждения, если денег может не хватить.</p>
      <label class="field">Email или логин
        <input v-model="login" autocomplete="username" maxlength="254" required autofocus />
      </label>
      <label class="field">Пароль
        <input v-model="password" type="password" autocomplete="current-password" required />
      </label>
      <p v-if="error" class="error form-error" role="alert">{{ error }}</p>
      <p v-if="needsVerification" class="foot-link"><RouterLink to="/register?resend=1">Отправить письмо подтверждения</RouterLink></p>
      <button class="btn btn-primary submit" :disabled="busy || !login || !password">{{ busy ? 'Входим…' : 'Войти' }}</button>

      <div class="or" role="separator"><span>или</span></div>

      <a v-if="SSO_CENTRINVEST_URL" class="btn submit" :href="SSO_CENTRINVEST_URL"><Landmark />Войти через Центр-инвест</a>
      <button v-else type="button" class="btn submit sso-off" disabled aria-describedby="sso-note">
        <Landmark />Войти через Центр-инвест <span class="chip">скоро</span>
      </button>
      <p v-if="!SSO_CENTRINVEST_URL" id="sso-note" class="tiny sso-note">Вход через банк подключим, как только его откроет банк.</p>

      <p class="foot-link">Нет аккаунта? <RouterLink to="/register">Зарегистрироваться</RouterLink></p>
    </form>
  </AuthLayout>
</template>

<style scoped>
.form-error { margin: -4px 0 16px; }
.or { display: flex; align-items: center; gap: 12px; margin: 20px 0; color: var(--ink-3); font-size: 14px; }
.or::before, .or::after { content: ''; flex: 1; height: 1px; background: var(--line); }
.sso-off { opacity: 1; color: var(--ink-3); background: var(--surface-2); border-color: var(--line); }
.sso-note { text-align: center; margin-top: 8px; }
</style>
