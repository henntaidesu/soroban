<template>
  <div>
    <div class="bar">
      <h2 class="page-title">全部订单</h2>
      <span class="hint">一个淘宝号下的所有订单都放这里（一单可多物），逐单点「导入」才进入账本。（将来爬虫自动灌入）</span>
    </div>

    <el-card>
      <NotionTable :columns="columns" :rows="rows" :loading="loading" expandable
                   table-name="staging" :actions-width="128" @save="saveCell" @add="addRow" @delete="doDelete">
        <template #toolbar>
          <el-select v-model="filters.status" placeholder="全部状态" clearable style="width: 130px" @change="reload">
            <el-option v-for="s in STAGING_STATUS" :key="s" :label="s" :value="s" />
          </el-select>
          <el-input v-model="filters.taobao_account" placeholder="淘宝账号" clearable style="width: 130px" @change="reload" />
          <el-input v-model="filters.q" placeholder="搜订单号/店铺" clearable style="width: 160px" @change="reload" />
        </template>

        <template #cell-items="{ row }">
          <span :class="row.items && row.items.length ? '' : 'ph'">{{ itemSummary(row) }}</span>
        </template>
        <template #cell-status="{ row }">
          <el-tag :type="stagingTag(row.status)" size="small" effect="dark">{{ row.status }}</el-tag>
        </template>

        <template #expand="{ row }">
          <div class="expand">
            <div class="ex-title">物品明细（一单多物）</div>
            <div v-for="(it, i) in row.items" :key="i" class="item-row">
              <el-input v-model="it.name" size="small" placeholder="物品名" style="width: 180px" />
              <el-input-number v-model="it.quantity" :min="1" size="small" />
              <el-button link type="danger" :icon="Delete" @click="row.items.splice(i, 1)" />
            </div>
            <div>
              <el-button size="small" :icon="Plus" @click="ensureItems(row).push({ name: '', quantity: 1 })">加物品</el-button>
              <el-button size="small" type="primary" @click="saveItems(row)">保存物品</el-button>
            </div>
          </div>
        </template>

        <template #actions="{ row }">
          <template v-if="row.imported_taobao_order_id">
            <el-tag type="success" size="small">已导入 #{{ row.imported_taobao_order_id }}</el-tag>
          </template>
          <template v-else>
            <el-button size="small" type="primary" @click="doImport(row)">导入</el-button>
            <el-button v-if="row.status !== '已忽略'" size="small" link @click="doIgnore(row)">忽略</el-button>
          </template>
        </template>
      </NotionTable>

      <el-pagination class="pager" layout="prev, pager, next, total" :total="total"
                     :page-size="pageSize" :current-page="page" @current-change="onPage" />
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Plus } from '@element-plus/icons-vue'
import { stagingApi } from '@/api'
import { TAOBAO_STATUS } from '@/constants'
import NotionTable from '@/components/NotionTable.vue'

const STAGING_STATUS = ['待处理', '已导入', '已忽略']
const stagingTag = (s) => ({ 待处理: 'warning', 已导入: 'success', 已忽略: 'info' }[s] || 'info')

const columns = [
  { key: 'order_date', label: '下单日期', type: 'date', width: 140 },
  { key: 'order_no', label: '订单号', type: 'text', minWidth: 130, placeholder: '订单号' },
  { key: 'shop', label: '店铺', type: 'text', minWidth: 110 },
  { key: 'price_cny', label: '人民币', type: 'decimal', format: 'cny', width: 100 },
  { key: 'fx_rate', label: '汇率', type: 'decimal', width: 80, placeholder: '当天' },
  { key: 'taobao_account', label: '淘宝号', type: 'text', width: 100 },
  { key: 'express_no', label: '快递号', type: 'text', width: 110 },
  { key: 'items', label: '物品', readonly: true, minWidth: 140, expand: true },
  { key: 'order_status', label: '订单状态', type: 'select', options: TAOBAO_STATUS, width: 100 },
  { key: 'status', label: '导入状态', readonly: true, width: 90 },
]

const rows = ref([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = 50
const filters = reactive({ status: '', taobao_account: '', q: '' })

function itemSummary(row) {
  if (!row.items || !row.items.length) return '—'
  return row.items.map((it) => `${it.name}×${it.quantity}`).join('，')
}
function ensureItems(row) {
  if (!row.items) row.items = []
  return row.items
}

async function load() {
  loading.value = true
  try {
    const params = { limit: pageSize, offset: (page.value - 1) * pageSize }
    if (filters.status) params.status = filters.status
    if (filters.taobao_account) params.taobao_account = filters.taobao_account
    if (filters.q) params.q = filters.q
    const res = await stagingApi.list(params)
    rows.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}
function reload() { page.value = 1; load() }
function onPage(p) { page.value = p; load() }

async function saveCell(row, key, value) {
  try {
    const updated = await stagingApi.update(row.id, { [key]: value })
    const { items, ...rest } = updated       // 不覆盖展开面板里未保存的物品编辑
    Object.assign(row, rest)
  } catch (e) {
    if (e.response?.status === 409) {
      ElMessage.warning(e.response?.data?.detail || '订单号已存在，未保存')
      load()   // 冲突：刷新回退到服务器状态
    }
    // 非 409：拦截器已提示，单元格自动显示旧值，无需整页重拉
  }
}

async function saveItems(row) {
  const items = (row.items || []).filter((it) => it.name && it.name.trim())
    .map((it) => ({ name: it.name.trim(), quantity: Number(it.quantity) || 1 }))
  try {
    const updated = await stagingApi.update(row.id, { items })
    Object.assign(row, updated)
    ElMessage.success('物品已保存')
  } catch (_) { load() }
}

async function addRow(data = {}) {
  try {
    const created = await stagingApi.create({ ...data })
    rows.value.unshift(created)
    total.value++
  } catch (_) { /* 拦截器已提示 */ }
}

async function doImport(row) {
  try {
    await stagingApi.import(row.id)
    ElMessage.success('已导入到淘宝订单账本')
    load()
  } catch (e) {
    if (e.response?.status === 409) {
      await ElMessageBox.alert(e.response?.data?.detail || '导入冲突', '导入失败', { type: 'warning' })
    }
  }
}
async function doIgnore(row) {
  try {
    await stagingApi.ignore(row.id)
    load()
  } catch (_) { /* 拦截器已提示 */ }
}
async function doDelete(row) {
  try {
    await ElMessageBox.confirm('删除这条暂存记录？', '确认', { type: 'warning' })
  } catch (_) { return }
  try {
    await stagingApi.remove(row.id)
    ElMessage.success('已删除')
    load()
  } catch (_) { /* 拦截器已提示 */ }
}

onMounted(load)
</script>

<style scoped>
.bar { display: flex; align-items: baseline; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
.hint { color: #7d8aa3; font-size: 13px; }
.pager { margin-top: 12px; justify-content: flex-end; }
.ph { color: #5b6880; }
.expand { padding: 12px 20px; }
.ex-title { color: #9ba8bf; font-size: 13px; margin-bottom: 8px; }
.item-row { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; }
</style>
