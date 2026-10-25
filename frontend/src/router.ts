import { createRouter, createWebHistory } from 'vue-router'
import { isLoggedIn } from './api'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/companies' },
    { path: '/login', component: () => import('./views/LoginView.vue'), meta: { public: true } },
    { path: '/register', component: () => import('./views/RegisterView.vue'), meta: { public: true } },
    { path: '/verify-email', component: () => import('./views/VerifyEmailView.vue'), meta: { public: true } },
    { path: '/companies', component: () => import('./views/CompaniesView.vue') },
    {
      path: '/companies/:id',
      component: () => import('./views/CompanyLayout.vue'),
      children: [
        { path: '', component: () => import('./views/ForecastView.vue'), meta: { title: 'Главная' } },
        { path: 'models', component: () => import('./views/ModelsView.vue'), meta: { title: 'Модели' } },
        { path: 'scenarios', component: () => import('./views/ScenariosView.vue') },
        { path: 'operations', component: () => import('./views/OperationsView.vue') },
        { path: 'plan-fact', component: () => import('./views/PlanFactView.vue') },
        { path: 'sources', component: () => import('./views/SourcesView.vue') },
      ],
    },
  ],
})

// VITE_NO_AUTH=1 — локальный просмотр с бэкендом CASHFLOW_DEV_NO_AUTH=1: вход не нужен.
const noAuth = import.meta.env.VITE_NO_AUTH === '1'
router.beforeEach((to) => {
  if (!to.meta.public && !noAuth && !isLoggedIn()) return '/login'
  if (to.meta.public && isLoggedIn() && (to.path === '/login' || to.path === '/register')) return '/companies'
  return true
})
