<script setup lang="ts">
withDefaults(defineProps<{ name: string; size?: number }>(), { size: 22 })
const paths: Record<string, string[]> = {
  forecast: ['M3 12 12 3l9 9', 'M5 10v11h14V10', 'M9 21v-7h6v7'],
  operations: ['M6 3h9l4 4v14H6z', 'M14 3v5h5', 'M9 12h7M9 16h5'],
  scenarios: ['M6 3h13v18H6z', 'M9 3v3h7V3', 'M9 10h7M9 14h7M9 18h4'],
  chart: ['M4 21V10h4v11M10 21V3h4v18M16 21V7h4v14'],
  sources: ['m4 8 4 4 4-8', 'M15 5h5v15H5v-4', 'M15 10h5M11 15h9'],
  search: ['M10.5 18a7.5 7.5 0 1 0 0-15 7.5 7.5 0 0 0 0 15Z', 'm16 16 5 5'],
  building: ['M3 21h18M6 21V5l9-3v19M15 9h4v12', 'M9 7v1M12 6v1M9 11v1M12 10v1M9 15v1M12 14v1'],
  people: ['M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z', 'M2 21v-3a7 7 0 0 1 14 0v3M17 4a4 4 0 0 1 0 8M19 15a5 5 0 0 1 3 5v1'],
  box: ['m12 2 9 5v10l-9 5-9-5V7z', 'm3 7 9 5 9-5M12 12v10M7 4.8l9 5'],
  tax: ['M5 3h10l4 4v14H5z', 'M8 7h4M8 11h3M12 17l5-5', 'M13 12h.01M16 17h.01'],
  bolt: ['m13 2-9 12h7l-1 8 10-13h-8z'],
  payment: ['M3 6h18v14H3z', 'M3 10h18M6 16h4'],
  warning: ['m12 3 10 18H2L12 3Z', 'M12 9v5M12 17h.01'],
  calendar: ['M4 5h16v16H4z', 'M8 2v6M16 2v6M4 10h16'],
  logout: ['M9 3H3v18h6M10 12h11m-4-4 4 4-4 4'],
  back: ['m12 5-7 7 7 7M5 12h16'],
}
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path v-for="(d, i) in paths[name] ?? paths.operations" :key="i" :d="d" />
  </svg>
</template>
