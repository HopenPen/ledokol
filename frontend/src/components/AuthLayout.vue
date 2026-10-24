<script setup lang="ts">
import BrandLogo from './BrandLogo.vue'
</script>

<template>
  <main class="auth">
    <section class="card auth-card">
      <RouterLink to="/login" class="brand"><BrandLogo /></RouterLink>
      <slot />
    </section>
  </main>
</template>

<style scoped>
.auth { min-height: 100dvh; display: grid; place-items: center; padding: 32px 16px; background: #f7f8f7; }
.auth-card { width: min(540px, 100%); padding: 48px 52px; border: 0; box-shadow: 0 6px 32px rgb(20 28 32 / 0.06); }
.brand { display: flex; justify-content: center; text-decoration: none; margin-bottom: 36px; }
.auth-card :deep(h1) { font-size: 30px; line-height: 1.2; text-align: center; }
.auth-card :deep(.lead) { color: var(--ink-2); margin: 12px 0 28px; text-align: center; }
.auth-card :deep(.submit) { width: 100%; min-height: 48px; margin-top: 8px; }
.auth-card :deep(.foot) { text-align: center; margin: 20px 0 0; font-size: 14px; }
.auth-card :deep(a) { color: var(--green); }
.auth-card :deep(.hint) { color: var(--muted); font-size: 13px; }
@media (max-width: 600px) { .auth-card { padding: 32px 24px; } .auth-card :deep(h1) { font-size: 26px; } }
</style>
