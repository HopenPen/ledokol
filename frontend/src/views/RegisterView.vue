<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
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
const delivery = ref<Awaited<ReturnType<typeof api.registrationInfo>> | null>(null)
const loadingDelivery = ref(true)
const deliveryError = ref('')
const canSend = computed(() => !!delivery.value && delivery.value.email_delivery !== 'unavailable')
const timer = setInterval(() => { if (cooldown.value > 0) cooldown.value-- }, 1000)
onUnmounted(() => clearInterval(timer))

async function loadDelivery() {
  loadingDelivery.value = true
  deliveryError.value = ''
  try { delivery.value = await api.registrationInfo() }
  catch { deliveryError.value = 'Не удалось проверить доступность регистрации. Повторите проверку.' }
  finally { loadingDelivery.value = false }
}
onMounted(loadDelivery)

async function submit(resend = false) {
  if (busy.value || !canSend.value) return
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
    <p v-if="loadingDelivery" class="hint" role="status">Проверяем доступность регистрации…</p>
    <div v-else-if="deliveryError" class="delivery-notice" role="alert">
      <p>{{ deliveryError }}</p>
      <button class="btn" @click="loadDelivery">Повторить проверку</button>
    </div>
    <div v-else-if="delivery?.email_delivery === 'unavailable'" class="delivery-notice" role="status">
      <strong>Регистрация пока недоступна</strong>
      <p>Отправка подтверждений ещё не подключена. Попросите администратора настроить почту. Если аккаунт уже подтверждён, вы можете войти.</p>
    </div>
    <div v-else-if="delivery?.email_delivery === 'local'" class="delivery-notice" role="status">
      <strong>Включена тестовая почта</strong>
      <p>Письма остаются в тестовом ящике и не приходят на ваш настоящий email.</p>
      <a v-if="delivery.local_mailbox_url" :href="delivery.local_mailbox_url" target="_blank" rel="noopener noreferrer">Открыть тестовую почту</a>
    </div>
    <template v-if="sent">
      <h1>{{ delivery?.email_delivery === 'local' ? 'Проверьте тестовую почту' : 'Проверьте почту' }}</h1>
      <p class="lead">{{ message }}</p>
      <p class="hint">Адрес: {{ email }}. Откройте письмо и перейдите по ссылке подтверждения.</p>
      <p class="hint">Если вы уже регистрировались, запросите письмо повторно кнопкой ниже. Для подтверждённого аккаунта новое письмо не требуется.</p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <button class="btn submit" :disabled="busy || cooldown > 0 || !canSend" @click="submit(true)">
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
      <button class="btn btn-primary submit" :disabled="busy || !canSend">
        {{ busy ? 'Отправляем…' : resendOnly ? 'Отправить ссылку' : 'Зарегистрироваться' }}
      </button>
      <p v-if="!resendOnly" class="hint">После регистрации подтвердите email по ссылке из письма.</p>
      <p class="foot">Уже есть аккаунт? <RouterLink to="/login">Войти</RouterLink></p>
    </form>
  </AuthLayout>
</template>

<style scoped>
.delivery-notice { margin-bottom: 24px; padding: 16px; border: 1px solid var(--line); border-radius: var(--radius-s); background: var(--paper); font-size: 14px; }
.delivery-notice p { margin: 8px 0; color: var(--ink-2); }
.delivery-notice a { text-underline-offset: 3px; }
</style>
