<script setup lang="ts">
import AppLogo from './AppLogo.vue'
</script>

<template>
  <main class="auth">
    <aside class="pitch" aria-hidden="true">
      <AppLogo />
      <div class="pitch-text">
        <p class="claim">Узнайте заранее, когда денег на счёте может не хватить.</p>
        <p class="sub">Дата, сумма и причина. Плюс что можно сделать, пока не поздно.</p>
      </div>
      <!-- Декоративная линия остатка: идёт вперёд и обходит зону ниже порога. -->
      <svg class="line" viewBox="0 0 400 140" preserveAspectRatio="none">
        <rect x="0" y="104" width="400" height="36" fill="rgb(255 255 255 / 0.06)" />
        <line x1="0" y1="104" x2="400" y2="104" stroke="rgb(255 255 255 / 0.35)" stroke-dasharray="4 6" />
        <path d="M0 70 C 50 60, 80 40, 120 52 S 190 98, 230 92 S 300 30, 340 36 S 390 24, 400 20"
              fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" />
      </svg>
      <p class="foot">Сервер в России. Данные видите только вы.</p>
    </aside>
    <section class="form-side">
      <div class="form-wrap">
        <AppLogo class="mobile-logo" />
        <slot />
      </div>
    </section>
  </main>
</template>

<style scoped>
.auth { min-height: 100dvh; display: grid; grid-template-columns: minmax(360px, 5fr) 7fr; }
.pitch {
  background: var(--brand); color: #fff; padding: 40px; display: flex; flex-direction: column; gap: 32px;
}
.pitch :deep(.logo) { color: #fff; }
.pitch :deep(.logo .mark-bg) { fill: #fff; }
.pitch :deep(.logo .mark-fg) { stroke: var(--brand); }
.pitch-text { margin-top: auto; display: grid; gap: 12px; max-width: 30ch; }
.claim { font-size: 30px; line-height: 1.15; font-weight: 650; letter-spacing: -0.02em; }
.sub { color: rgb(255 255 255 / 0.8); }
.line { width: 100%; height: 140px; }
.foot { color: rgb(255 255 255 / 0.75); font-size: 14px; }
.form-side { display: grid; place-items: center; padding: 40px 24px; background: var(--surface); }
.form-wrap { width: min(400px, 100%); }
.mobile-logo { display: none; margin-bottom: 32px; }
.form-wrap :deep(h1) { margin-bottom: 8px; }
.form-wrap :deep(.lead) { color: var(--ink-2); margin-bottom: 28px; }
.form-wrap :deep(.submit) { width: 100%; min-height: 48px; }
.form-wrap :deep(.foot-link) { text-align: center; margin-top: 24px; font-size: 15px; color: var(--ink-2); }
@media (max-width: 860px) {
  .auth { grid-template-columns: 1fr; }
  .pitch { display: none; }
  .mobile-logo { display: inline-flex; }
  .form-side { place-items: start center; }
}
</style>
