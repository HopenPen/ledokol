<template>
  <main class="auth">
    <section class="card auth-card">
      <RouterLink to="/login" class="brand">Деньги вперёд</RouterLink>
      <slot />
    </section>
  </main>
</template>

<style scoped>
.auth { min-height: 100vh; display: grid; place-items: center; padding: 24px 16px; }
.auth-card { width: min(420px, 100%); padding: 32px; }
.brand { display: block; color: var(--green); font-weight: 600; text-decoration: none; margin-bottom: 24px; }
.auth-card :deep(h1) { font-size: 28px; line-height: 1.2; }
.auth-card :deep(.lead) { color: var(--ink-2); margin: 12px 0 24px; }
.auth-card :deep(.submit) { width: 100%; margin-top: 4px; }
.auth-card :deep(.foot) { text-align: center; margin: 20px 0 0; font-size: 14px; }
.auth-card :deep(a) { color: var(--green); }
.auth-card :deep(.hint) { color: var(--muted); font-size: 13px; }
</style>
