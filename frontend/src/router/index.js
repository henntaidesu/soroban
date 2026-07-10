import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login/index.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    component: () => import('@/components/Layout.vue'),
    children: [
      { path: '', redirect: '/dashboard' },
      { path: 'dashboard', name: 'Dashboard', component: () => import('@/views/Dashboard/index.vue'), meta: { title: '看板', icon: 'Odometer' } },
      { path: 'staging', name: 'Staging', component: () => import('@/views/Staging/index.vue'), meta: { title: '全部淘宝订单', icon: 'Inbox' } },
      { path: 'taobao', name: 'Taobao', component: () => import('@/views/Taobao/index.vue'), meta: { title: '淘宝订单', icon: 'ShoppingCart' } },
      { path: 'junfeng', name: 'Junfeng', component: () => import('@/views/Junfeng/index.vue'), meta: { title: '君丰订单', icon: 'Ship' } },
      { path: 'misc', name: 'Misc', component: () => import('@/views/Misc/index.vue'), meta: { title: '杂项支出', icon: 'Money' } },
    ],
  },
]

const router = createRouter({ history: createWebHashHistory(), routes })

router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('auth_token')
  if (!to.meta?.public && !token) return next('/login')
  if (to.path === '/login' && token) return next('/dashboard')
  next()
})

export default router
