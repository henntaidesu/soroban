<template>
  <div>
    <div class="bar">
      <span class="hint">soroban 自动扫描 scraper/ 下 soroban-scraper-* 目录作为插件。登录授权、参数、定时都在这里管；插件本体只管抓取。抓到的订单进「全部订单」待处理。</span>
      <el-button size="small" :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </div>

    <el-empty v-if="!loading && !plugins.length" description="未发现插件（scraper/ 下没有 soroban-scraper-* 目录）" />

    <el-card v-for="p in plugins" :key="p.id" class="plugin" v-loading="p._busy">
      <template #header>
        <div class="head">
          <span class="pname">{{ p.name }}</span>
          <span class="pver">v{{ p.version || '?' }}</span>
          <el-tag size="small" :style="typeStyle(p.installed ? 'success' : 'danger')">
            {{ p.installed ? '已安装' : '未安装(缺 venv)' }}
          </el-tag>
          <div class="grow" />
          <span class="sw-label">启用定时</span>
          <el-switch v-model="p._form.enabled" :disabled="!p.installed" @change="saveConfig(p)" />
        </div>
      </template>

      <!-- 参数 -->
      <div class="field" v-for="par in p.params" :key="par.key">
        <label class="flabel">{{ par.label || par.key }}</label>
        <el-switch v-if="par.type === 'bool'" v-model="p._form.params[par.key]" />
        <el-input-number v-else-if="par.type === 'number' || par.type === 'int'"
                         v-model="p._form.params[par.key]" :min="0" />
        <el-input v-else v-model="p._form.params[par.key]" :placeholder="String(par.default ?? '')" style="max-width: 360px" />
      </div>

      <!-- 定时 -->
      <div class="field">
        <label class="flabel">定时抓取（分钟，0=关闭）</label>
        <el-input-number v-model="p._form.schedule_minutes" :min="0" :step="30" />
        <span class="sub">{{ p.config.last_run_at ? '上次：' + fmtTime(p.config.last_run_at) : '尚未抓取' }}</span>
      </div>

      <div class="field">
        <el-button type="primary" size="small" @click="saveConfig(p)">保存配置</el-button>
      </div>

      <!-- 账号授权 -->
      <div class="sect">账号授权</div>
      <div v-if="!p.accounts.length" class="sub">配置里还没填账号（保存后此处出现每个账号的授权状态）。</div>
      <div v-for="a in p.accounts" :key="a.account" class="acct">
        <span class="aname">{{ a.account }}</span>
        <el-tag size="small" :style="typeStyle(a.authorized ? 'success' : 'warning')">
          {{ a.authorized ? '已授权' : '未授权' }}
        </el-tag>
        <el-tag v-if="!a.configured" size="small" :style="typeStyle('info')"
                title="磁盘上有此账号的登录会话，但未写入插件配置。把它填进上面的「账号」并保存，定时抓取才会带上它。">
          未入库
        </el-tag>
        <el-button size="small" link type="primary" :disabled="!p.installed" @click="doLogin(p, a.account)">
          {{ a.authorized ? '重新授权' : '授权登录' }}
        </el-button>
        <el-button size="small" link :disabled="!p.installed || !a.authorized" @click="doFetch(p, a.account)">
          抓这个号
        </el-button>
        <el-button size="small" link type="danger" @click="doDeleteAccount(p, a.account)">
          删除
        </el-button>
      </div>

      <div class="field" style="margin-top: 12px">
        <el-button size="small" :icon="Download" :disabled="!p.installed || !p.accounts.length" @click="doFetch(p)">
          抓取全部账号
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Download } from '@element-plus/icons-vue'
import { pluginsApi } from '@/api'
import { typeStyle } from '@/constants'

const plugins = ref([])
const loading = ref(false)

function fmtTime(s) {
  const d = new Date(s)
  return isNaN(d) ? s : d.toLocaleString('ja-JP')
}

// 把服务端配置铺到可编辑表单：参数缺省用 manifest 默认值兜底
function toForm(p) {
  const params = {}
  for (const par of p.params || []) {
    params[par.key] = p.config.params?.[par.key] ?? par.default ?? ''
  }
  return { enabled: p.config.enabled, params, schedule_minutes: p.config.schedule_minutes || 0 }
}

async function load() {
  loading.value = true
  try {
    const list = await pluginsApi.list()
    plugins.value = list.map((p) => ({ ...p, _busy: false, _form: toForm(p) }))
  } catch (_) { /* 拦截器已提示 */ } finally {
    loading.value = false
  }
}

async function saveConfig(p) {
  p._busy = true
  try {
    await pluginsApi.saveConfig(p.id, {
      enabled: p._form.enabled,
      params: p._form.params,
      schedule_minutes: p._form.schedule_minutes,
    })
    ElMessage.success('已保存')
    await load()
  } catch (_) { /* 拦截器已提示 */ } finally {
    p._busy = false
  }
}

async function doLogin(p, account) {
  try {
    await pluginsApi.login(p.id, account)
    ElMessage.success(`已启动 ${account} 的登录，请在弹出的浏览器完成登录后点「刷新」`)
  } catch (_) { /* 拦截器已提示 */ }
}

async function doFetch(p, account) {
  try {
    await pluginsApi.fetch(p.id, account)
    ElMessage.success(account ? `已触发抓取：${account}` : '已触发抓取（全部账号）')
  } catch (_) { /* 拦截器已提示 */ }
}

async function doDeleteAccount(p, account) {
  try {
    await ElMessageBox.confirm(
      `确定删除账号「${account}」的授权？会删掉本地登录会话并移出配置，之后需重新扫码登录才能再抓这个号。`,
      '删除账号授权', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch (_) { return }   // 用户取消
  p._busy = true
  try {
    await pluginsApi.deleteAccount(p.id, account)
    ElMessage.success(`已删除 ${account} 的授权`)
    await load()
  } catch (_) { /* 拦截器已提示 */ } finally {
    p._busy = false
  }
}

onMounted(load)
</script>

<style scoped>
.bar { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.hint { color: #7d8aa3; font-size: 12px; flex: 1; }
.plugin { margin-bottom: 16px; }
.head { display: flex; align-items: center; gap: 10px; }
.pname { color: #e6edf7; font-size: 15px; font-weight: 600; }
.pver { color: #7d8aa3; font-size: 12px; }
.grow { flex: 1; }
.sw-label { color: #9ba8bf; font-size: 13px; }
.field { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.flabel { color: #9ba8bf; font-size: 13px; min-width: 180px; }
.sub { color: #7d8aa3; font-size: 12px; }
.sect { color: #c7d2e6; font-size: 13px; font-weight: 600; margin: 6px 0 10px; padding-top: 12px; border-top: 1px solid #1c2740; }
.acct { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.aname { color: #e6edf7; font-size: 14px; min-width: 120px; }
</style>
