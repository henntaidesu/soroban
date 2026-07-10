<template>
  <div>
    <h2 class="page-title">君丰订单</h2>

    <el-card>
      <NotionTable :columns="columns" :rows="rows" :loading="loading" expandable
                   table-name="junfeng" @save="saveCell" @add="addRow">
        <template #toolbar>
          <el-date-picker v-model="filters.range" type="daterange" value-format="YYYY-MM-DD"
                          start-placeholder="起" end-placeholder="止" @change="reload" />
          <el-select v-model="filters.status" placeholder="状态" clearable style="width: 110px" @change="reload">
            <el-option v-for="s in JUNFENG_STATUS" :key="s" :label="s" :value="s" />
          </el-select>
          <el-input v-model="filters.q" placeholder="搜君丰单号" clearable style="width: 150px" @change="reload" />
        </template>

        <template #expand="{ row }">
          <div class="expand">
            <div class="ex-title">关联淘宝订单（只读；在「淘宝订单」页的「君丰(点选)」列挂靠）</div>
            <el-table v-if="row.taobao_orders && row.taobao_orders.length" :data="row.taobao_orders" size="small">
              <el-table-column prop="order_no" label="订单号" min-width="130" />
              <el-table-column prop="date" label="日期" width="120" />
              <el-table-column prop="shop" label="店铺" min-width="100" />
              <el-table-column label="状态" width="80">
                <template #default="{ row: t }"><el-tag :type="statusTagType(t.status)" size="small" effect="dark">{{ t.status }}</el-tag></template>
              </el-table-column>
              <el-table-column label="结算¥" width="110">
                <template #default="{ row: t }">{{ fmtJPY(t.jpy_settled) }}</template>
              </el-table-column>
            </el-table>
            <span v-else class="ph">无（在淘宝订单页把订单挂到本单）</span>
          </div>
        </template>

        <template #actions="{ row }">
          <el-button size="small" link type="danger" @click="delRow(row)">删除</el-button>
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
import { junfengApi } from '@/api'
import { JUNFENG_STATUS, statusTagType } from '@/constants'
import { fmtJPY } from '@/utils/money'
import NotionTable from '@/components/NotionTable.vue'

const today = () => new Date().toISOString().slice(0, 10)

const columns = [
  { key: 'date', label: '日期', type: 'date', width: 130 },
  { key: 'junfeng_no', label: '君丰单号', type: 'text', minWidth: 120, placeholder: '君丰单号' },
  { key: 'intl_tracking_no', label: '国际运单号', type: 'text', minWidth: 120 },
  { key: 'weight', label: '重量kg', type: 'decimal', width: 80 },
  { key: 'status', label: '状态', type: 'select', options: JUNFENG_STATUS, width: 100 },
  { key: 'price_cny', label: '运费(元)', type: 'decimal', format: 'cny', width: 95 },
  { key: 'fx_rate', label: '汇率', type: 'decimal', width: 75 },
  { key: 'special_fee_jpy', label: '特殊费¥', type: 'int', width: 95, placeholder: '关税/消费税' },
  { key: 'jpy_override', label: '覆盖¥', type: 'int', format: 'jpy', width: 95, placeholder: '实付日元' },
  { key: 'jpy_settled', label: '结算¥', format: 'jpy', readonly: true, width: 100 },
]

const rows = ref([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = 30
const filters = reactive({ range: null, status: '', q: '' })

async function load() {
  loading.value = true
  try {
    const params = { limit: pageSize, offset: (page.value - 1) * pageSize }
    if (filters.range) { params.date_from = filters.range[0]; params.date_to = filters.range[1] }
    if (filters.status) params.status = filters.status
    if (filters.q) params.q = filters.q
    const res = await junfengApi.list(params)
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
    const updated = await junfengApi.update(row.id, { version: row.version, [key]: value })
    Object.assign(row, updated)
  } catch (e) {
    if (e.response?.status === 409) { ElMessage.warning(e.response?.data?.detail || '数据已变，已刷新'); load() }
  }
}

async function addRow(data = {}) {
  try {
    const created = await junfengApi.create({ date: today(), status: '打包中', ...data })
    rows.value.unshift(created)
    total.value++
  } catch (_) { /* 拦截器已提示 */ }
}

async function delRow(row) {
  try {
    await ElMessageBox.confirm(`删除君丰订单 ${row.junfeng_no || row.id}？`, '确认', { type: 'warning' })
  } catch (_) { return }
  try {
    await junfengApi.remove(row.id)
    rows.value = rows.value.filter((r) => r.id !== row.id)
    total.value--
    ElMessage.success('已删除')
  } catch (_) { /* 拦截器已提示 */ }
}

onMounted(load)
</script>

<style scoped>
.pager { margin-top: 12px; justify-content: flex-end; }
.ph { color: #5b6880; }
.expand { padding: 12px 20px; }
.ex-title { color: #9ba8bf; font-size: 13px; margin-bottom: 8px; }
.tag { margin-right: 6px; }
</style>
