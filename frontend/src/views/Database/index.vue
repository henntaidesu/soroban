<template>
  <div class="db-page">
    <h2 class="title">数据库</h2>

    <!-- 当前状态 -->
    <el-card shadow="never" class="card">
      <div class="card-hd">
        <span>当前后端</span>
        <el-tag :type="status.backend === 'mysql' ? 'success' : 'info'" effect="dark">
          {{ status.backend === 'mysql' ? 'MySQL' : 'SQLite（本地文件）' }}
        </el-tag>
      </div>
      <div v-if="status.mysql" class="status-detail">
        {{ status.mysql.user }}@{{ status.mysql.host }}:{{ status.mysql.port }} / {{ status.mysql.database }}
      </div>
    </el-card>

    <!-- 已在 MySQL：只展示状态 -->
    <el-alert
      v-if="status.backend === 'mysql'"
      type="success" :closable="false" show-icon
      title="已迁移到 MySQL"
      description="业务数据当前由 MySQL 提供。若要更换 MySQL 或切回 SQLite，请在后端 .env / 数据库层面操作后重启。"
      class="card"
    />

    <!-- 未迁移：MySQL 连接表单 -->
    <el-card v-else shadow="never" class="card">
      <div class="card-hd"><span>迁移到 MySQL</span></div>
      <el-form :model="form" label-width="92px" class="form" @submit.prevent>
        <el-form-item label="主机">
          <el-input v-model="form.host" />
        </el-form-item>
        <el-form-item label="端口">
          <el-input v-model.number="form.port" placeholder="3306" style="max-width: 160px" />
        </el-form-item>
        <el-form-item label="用户名">
          <el-input v-model="form.user" name="soroban-mysql-user"
                    autocomplete="off" :readonly="ro.user" @focus="ro.user = false" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password
                    name="soroban-mysql-pass" autocomplete="new-password"
                    :readonly="ro.pass" @focus="ro.pass = false" />
        </el-form-item>
        <el-form-item label="数据库名">
          <el-input v-model="form.database" placeholder="soroban" />
        </el-form-item>
        <el-form-item>
          <el-button :loading="testing" @click="onTest">测试连接</el-button>
          <el-button type="primary" :loading="migrating" @click="onMigrate">迁移数据库</el-button>
          <el-button type="warning" :loading="switching" @click="onSwitch">切换数据库</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 迁移结果 -->
    <el-card v-if="result" shadow="never" class="card">
      <div class="card-hd"><span>迁移完成</span><el-tag type="success">共 {{ result.total }} 行</el-tag></div>
      <el-table :data="resultRows" size="small" style="width: 100%">
        <el-table-column prop="table" label="表" />
        <el-table-column prop="rows" label="行数" width="120" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { dbApi } from '@/api'

const status = reactive({ backend: 'sqlite', mysql: null })
const form = reactive({ host: '', port: 3306, user: '', password: '', database: 'soroban' })
// 初始 readonly，聚焦时解除 → 阻止浏览器加载时自动填充登录账号（用户名/密码）
const ro = reactive({ user: true, pass: true })
const testing = ref(false)
const migrating = ref(false)
const switching = ref(false)
const result = ref(null)
const resultRows = computed(() =>
  result.value ? Object.entries(result.value.counts).map(([table, rows]) => ({ table, rows })) : [])

async function loadStatus() {
  try {
    const s = await dbApi.status()
    status.backend = s.backend
    status.mysql = s.mysql || null
  } catch (_) { /* 拦截器已提示 */ }
}

async function onTest() {
  testing.value = true
  try {
    const r = await dbApi.test({ ...form })
    ElMessage.success(r.note ? r.note : `连接成功，MySQL ${r.version}`)
  } catch (_) { /* 拦截器已提示 */ } finally { testing.value = false }
}

async function onMigrate() {
  try {
    await ElMessageBox.confirm(
      '将建库、建表并把本地 SQLite 数据拷入 MySQL（目标库需为空）。此步不切换、不删除本地数据。确认继续？',
      '迁移数据库', { type: 'info', confirmButtonText: '开始迁移', cancelButtonText: '取消' },
    )
  } catch (_) { return }
  migrating.value = true
  try {
    const r = await dbApi.migrate({ ...form })
    result.value = r
    ElMessage.success(`迁移完成，共 ${r.total} 行。确认无误后可点「切换数据库」`)
  } catch (_) { /* 拦截器已提示 */ } finally { migrating.value = false }
}

async function onSwitch() {
  try {
    await ElMessageBox.confirm(
      '将立即热切换到 MySQL（无需重启），随后清空本地 SQLite 业务数据、仅保留系统配置。请确认已先完成「迁移数据库」。此操作不可撤销，确认继续？',
      '切换数据库', { type: 'warning', confirmButtonText: '切换到 MySQL', cancelButtonText: '取消' },
    )
  } catch (_) { return }
  switching.value = true
  try {
    await dbApi.switch({ ...form })
    ElMessage.success('已切换到 MySQL')
    await loadStatus()
  } catch (_) { /* 拦截器已提示 */ } finally { switching.value = false }
}

onMounted(loadStatus)
</script>

<style scoped>
.db-page { max-width: 720px; }
.title { margin: 0 0 16px; font-size: 20px; }
.card { margin-bottom: 16px; }
.card-hd { display: flex; align-items: center; justify-content: space-between; gap: 12px; font-weight: 600; margin-bottom: 10px; }
.status-detail { color: #606266; font-size: 13px; margin-bottom: 8px; }
.form { margin-top: 6px; }

/* 去掉浏览器自动填充（用户名/密码）留下的黄/蓝底色，保持与其它输入框一致 */
.form :deep(input:-webkit-autofill),
.form :deep(input:-webkit-autofill:hover),
.form :deep(input:-webkit-autofill:focus),
.form :deep(input:-webkit-autofill:active) {
  -webkit-box-shadow: 0 0 0 1000px var(--el-input-bg-color, transparent) inset !important;
  -webkit-text-fill-color: var(--el-input-text-color, inherit) !important;
  caret-color: var(--el-input-text-color, inherit);
  transition: background-color 99999s ease-out 0s !important;
}
</style>
