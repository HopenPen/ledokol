// Форматирование «по-человечески»: суммы до тысяч, даты словами, вероятность словами (ТЗ: интерфейс без терминов).

const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']

export function rub(x: number): string {
  const a = Math.abs(x)
  if (a >= 1e6) return `${(x / 1e6).toFixed(1).replace('.', ',')} млн ₽`
  if (a >= 1e3) return `${Math.round(x / 1e3)} тыс. ₽`
  return `${Math.round(x)} ₽`
}

export function humanDate(iso: string): string {
  const [, m, d] = iso.split('-').map(Number)
  return `${d} ${MONTHS[m - 1]}`
}

export const SOURCE_LABEL: Record<string, string> = {
  history: 'из истории', calendar: 'налоги', manual: 'вы добавили', '1c': '1С', scenario: 'сценарий',
}

export function chance(p: number): string {
  if (p >= 0.995) return ''
  return p >= 0.8 ? 'почти наверняка' : p >= 0.5 ? `скорее всего (${Math.round(p * 100)}%)` : `возможно (${Math.round(p * 100)}%)`
}
