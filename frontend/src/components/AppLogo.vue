<script setup lang="ts">
// Знак: стрелка «вперёд», выходящая из скобки — деньги, которые уже видно наперёд. Без чужих логотипов.
withDefaults(defineProps<{ compact?: boolean; size?: number }>(), { compact: false, size: 32 })
</script>

<template>
  <span class="logo" :class="{ compact }">
    <svg :width="size" :height="size" viewBox="0 0 32 32" aria-hidden="true">
      <rect class="mark-bg" width="32" height="32" rx="8" />
      <path d="M11 8.5H8.5v15H11" class="mark-fg" fill="none" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" />
      <path d="M13 16h11m-4.5-5L24 16l-4.5 5" class="mark-fg" fill="none" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
    <span v-if="!compact" class="word">Деньги, вперёд!</span>
  </span>
</template>

<style scoped>
.logo { display: inline-flex; align-items: center; gap: 10px; color: var(--ink); text-decoration: none; }
.mark-bg { fill: var(--brand); }
.mark-fg { stroke: #fff; }
.word { font-weight: 700; font-size: 18px; letter-spacing: -0.02em; white-space: nowrap; }
</style>
