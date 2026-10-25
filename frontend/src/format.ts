// Форматирование «по-человечески»: суммы словами «тыс./млн», даты словами, вероятность словами (ТЗ: без терминов).
import type { ImportResult } from './api'

export function importSummary(results: ImportResult[]): string {
  const added = results.reduce((sum, result) => sum + result.rows_new, 0)
  const rejected = results.reduce((sum, result) => sum + result.quality.rows_rejected, 0)
  const matched = results.reduce((sum, result) => sum + result.rows_matched, 0)
  const message = results.every((result) => result.already_imported)
    ? 'Эта выписка уже загружена' : `Добавлено операций: ${added}${matched ? `. Подтверждено ручных платежей: ${matched}` : ''}. Прогноз обновлён`
  return rejected ? `${message}. Строк с ошибками пропущено: ${rejected}` : message
}

const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
const MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']

/** Короткая сумма для заголовков и графиков: «340 тыс. ₽», «1,3 млн ₽». */
export function rub(x: number): string {
  const a = Math.abs(x)
  const sign = x < 0 ? '−' : ''
  if (a >= 1e6) return `${sign}${(a / 1e6).toFixed(1).replace('.', ',')} млн ₽`
  if (a >= 1e3) return `${sign}${Math.round(a / 1e3)} тыс. ₽`
  return `${sign}${Math.round(a)} ₽`
}

const fullFmt = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 2 })
/** Точная сумма для таблиц: «1 284 560 ₽». Минус — настоящий знак минуса, а не дефис. */
export function money(x: number | string): string {
  const n = Number(x)
  return `${n < 0 ? '−' : ''}${fullFmt.format(Math.abs(n))} ₽`
}

export function signed(amount: number | string, direction: string): string {
  return `${direction === 'in' ? '+' : '−'}${fullFmt.format(Math.abs(Number(amount)))} ₽`
}

export function humanDate(iso: string, withYear = false): string {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return `${d} ${MONTHS[m - 1]}${withYear ? ` ${y}` : ''}`
}

export function shortDate(iso: string): string {
  const [, m, d] = iso.slice(0, 10).split('-').map(Number)
  return `${d} ${MONTHS_SHORT[m - 1]}`
}

/** Календарные дни между двумя датами ISO. */
export function daysBetween(fromIso: string, toIso: string): number {
  return Math.round((Date.parse(toIso.slice(0, 10)) - Date.parse(fromIso.slice(0, 10))) / 86_400_000)
}

export function plural(n: number, one: string, few: string, many: string): string {
  const a = Math.abs(n) % 100
  const b = a % 10
  if (a > 10 && a < 20) return many
  if (b > 1 && b < 5) return few
  if (b === 1) return one
  return many
}

export function fileSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} МБ`
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} КБ`
  return `${bytes} Б`
}

/** Откуда сервис знает о будущем событии. */
export const SOURCE_LABEL: Record<string, string> = {
  history: 'регулярный', calendar: 'налог', manual: 'вы добавили', '1c': '1С', scenario: 'сценарий', fns: 'ФНС',
}

/** Как определена категория операции. */
export const CATEGORY_SOURCE: Record<string, string> = {
  rule: 'по правилу из назначения платежа', counterparty: 'по истории этого контрагента', ml: 'моделью по тексту',
  user: 'вы исправили вручную', none: 'не определена',
}

export const BALANCE_SOURCE: Record<string, string> = {
  statement: 'Подтверждён выпиской', calculated: 'Рассчитан с учётом ручных операций',
  initial: 'Начальный остаток', legacy: 'Ранее введён вручную', unknown: 'Неизвестен',
}

export function chanceWords(p: number): string {
  return p >= 0.8 ? 'наиболее вероятно' : p >= 0.5 ? 'вероятно' : 'наименее вероятно'
}

export function percent(p: number): string {
  return `${Math.round(p * 100)}%`
}
