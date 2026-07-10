<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-logo">算</span>
        <div class="brand-text">
          <div class="brand-title">算盤 soroban</div>
          <div class="brand-sub">代购集运记账</div>
        </div>
      </div>

      <el-menu router :default-active="$route.path" class="menu" background-color="#0f1728"
               text-color="#9ba8bf" active-text-color="#ffffff">
        <el-menu-item v-for="m in nav" :key="m.path" :index="m.path">
          <el-icon><component :is="m.icon" /></el-icon>
          <span>{{ m.title }}</span>
        </el-menu-item>
      </el-menu>

      <div class="foot">
        <div class="fx" v-if="fx.rate">
          1元 = {{ fx.rate }}円
          <el-tag v-if="fx.stale" size="small" type="warning" effect="dark">旧</el-tag>
        </div>
        <div class="user">
          <el-icon><User /></el-icon><span>{{ userName }}</span>
        </div>
        <el-button size="small" text bg @click="logout">退出登录</el-button>
      </div>
    </aside>

    <main class="content">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { fxApi } from '@/api'

const router = useRouter()
const nav = [
  { path: '/dashboard', title: '看板', icon: 'Odometer' },
  { path: '/staging', title: '全部订单', icon: 'Tickets' },
  { path: '/taobao', title: '淘宝订单', icon: 'ShoppingCart' },
  { path: '/shipment', title: '集运订单', icon: 'Ship' },
  { path: '/misc', title: '杂项支出', icon: 'Money' },
]

const userName = ref('用户')
try {
  const u = JSON.parse(localStorage.getItem('auth_user') || '{}')
  userName.value = u.display_name || u.username || '用户'
} catch (_) { /* ignore */ }

const fx = reactive({ rate: null, stale: false })
onMounted(async () => {
  try {
    const r = await fxApi.get()
    fx.rate = r.rate
    fx.stale = r.stale
  } catch (_) { /* ignore */ }
})

function logout() {
  localStorage.removeItem('auth_token')
  localStorage.removeItem('auth_user')
  router.push('/login')
}
</script>

<style scoped>
.layout { display: flex; height: 100vh; }
.sidebar {
  width: 220px; flex-shrink: 0; background: #0f1728;
  display: flex; flex-direction: column; border-right: 1px solid #1c2740;
}
.brand { display: flex; align-items: center; gap: 10px; padding: 18px 16px; }
.brand-logo {
  width: 40px; height: 40px; border-radius: 8px; background: #1890ff;
  color: #fff; font-size: 22px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
}
.brand-title { font-size: 15px; color: #e6edf7; font-weight: 600; }
.brand-sub { font-size: 12px; color: #7d8aa3; }
.menu { flex: 1; border-right: none; }
.menu :deep(.el-menu-item) { margin: 4px 8px; border-radius: 6px; }
.menu :deep(.el-menu-item.is-active) { background: #1890ff; }
.foot { padding: 12px 16px; border-top: 1px solid #1c2740; display: flex; flex-direction: column; gap: 8px; }
.fx { font-size: 13px; color: #9ba8bf; display: flex; align-items: center; gap: 6px; }
.user { display: flex; align-items: center; gap: 6px; color: #c7d2e6; font-size: 13px; }
.content { flex: 1; overflow: auto; padding: 20px; }
</style>
