/// <reference types="vite/client" />
declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}

interface ImportMetaEnv {
  /** Адрес входа через «Центр-инвест». Пусто — кнопка показывается неактивной с пометкой «скоро». */
  readonly VITE_SSO_CENTRINVEST_URL?: string
}
