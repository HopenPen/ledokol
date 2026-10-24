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
        { path: '', component: () => import('./views/ForecastView.vue') },
        { path: 'scenarios', component: () => import('./views/ScenariosView.vue') },
        { path: 'operations', component: () => import('./views/OperationsView.vue') },
        { path: 'plan-fact', component: () => import('./views/PlanFactView.vue') },
        { path: 'sources', component: () => import('./views/SourcesView.vue') },
      ],
    },
  ],
})

router.beforeEach((to) => (!to.meta.public && !isLoggedIn() ? '/login' : true))
