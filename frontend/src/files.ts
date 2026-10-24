// Форматы вложений: тот же белый список, что и на сервере (app/services/attachments.py).
export const ATTACH_ACCEPT = '.pdf,.png,.jpg,.jpeg,.webp,.heic,.txt,.csv,.xml,.doc,.docx,.xls,.xlsx,.odt,.ods'
export const ATTACH_EXT = new Set(ATTACH_ACCEPT.split(',').map((x) => x.slice(1)))
export const ATTACH_MAX_MB = 10
