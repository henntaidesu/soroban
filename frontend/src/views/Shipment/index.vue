<template>
  <div>
    <el-card>
      <NotionTable :columns="columns" :rows="rows" :loading="loading" expandable
                   table-name="shipment" @save="saveCell" @add="addRow" @delete="delRow" @reload="load">
        <template #toolbar>
          <el-date-picker v-model="filters.range" type="daterange" value-format="YYYY-MM-DD" class="flt-date"
                          start-placeholder="起" end-placeholder="止" @change="reload" />
          <el-select v-model="filters.status" placeholder="状态" clearable style="width: 110px" @change="reload">
            <el-option v-for="s in SHIPMENT_STATUS" :key="s" :label="s" :value="s" />
          </el-select>
          <el-input v-model="filters.q" placeholder="搜集运单号" clearable style="width: 150px" @change="reload" />
        </template>

        <template #cell-orders="{ row }">
          <span :class="row.orders && row.orders.length ? '' : 'ph'">{{ tbSummary(row) }}</span>
        </template>

        <template #expand="{ row }">
          <div class="expand">
            <div class="ex-title">关联商品订单（在此点选增删；商品页「集运(点选)」列也能改）</div>
            <el-table v-if="row.orders && row.orders.length" :data="row.orders" size="small">
              <el-table-column label="下单日期" width="110">
                <template #default="{ row: t }"><span :class="t.date ? '' : 'ph'">{{ t.date || '—' }}</span></template>
              </el-table-column>
              <el-table-column label="订单号" min-width="130">
                <template #default="{ row: t }">
                  <el-link type="primary" :underline="false" @click="gotoOrder(t)">{{ t.order_no || ('#' + t.id) }}</el-link>
                </template>
              </el-table-column>
              <el-table-column label="商品" min-width="160" show-overflow-tooltip>
                <template #default="{ row: t }"><span :class="t.shop ? '' : 'ph'">{{ t.shop || '—' }}</span></template>
              </el-table-column>
              <el-table-column label="物品" min-width="180">
                <template #default="{ row: t }">
                  <span :class="t.items && t.items.length ? '' : 'ph'">{{ itemSummary(t) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="结算（円）" width="110">
                <template #default="{ row: t }">{{ fmtJPY(t.jpy_settled) }}</template>
              </el-table-column>
              <el-table-column label="" width="72">
                <template #default="{ row: t }">
                  <el-button link type="danger" size="small" @click="detach(row, t)">移除</el-button>
                </template>
              </el-table-column>
            </el-table>
            <div v-else class="ph">暂无关联商品订单</div>
            <div class="add-line">
              <el-select :model-value="null" filterable placeholder="＋ 添加商品订单（未挂靠）"
                         size="small" class="tb-pick" @change="(id) => attach(row, id)">
                <el-option v-for="t in unassignedOptions" :key="t.id" :label="t.order_no || ('#' + t.id)" :value="t.id">
                  <div class="tb-opt">
                    <b>{{ t.order_no || ('#' + t.id) }}</b>
                    <span class="tb-meta">{{ itemSummary(t) }} · {{ fmtJPY(t.jpy_settled) }}</span>
                  </div>
                </el-option>
              </el-select>
              <span v-if="!unassignedOptions.length" class="ph small">没有未挂靠的商品订单</span>
            </div>
          </div>
        </template>

      </NotionTable>

      <el-pagination class="pager" layout="prev, pager, next, total" :total="total"
                     :page-size="pageSize" :current-page="page" @current-change="onPage" />
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { shipmentApi, ordersApi } from '@/api'
import { SHIPMENT_STATUS } from '@/constants'
import { fmtJPY } from '@/utils/money'
import NotionTable from '@/components/NotionTable.vue'

const router = useRouter()
// 点关联订单的订单号 → 跳到商品页、隔离显示该单并自动展开（用 id，兼容无订单号的单）
function gotoOrder(t) { router.push({ path: '/orders', query: { focus: t.id } }) }

// 用本地时区（用户在日本=JST）的当天，而非 UTC；否则 JST 0~9 点新建会记成前一天
const today = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const columns = [
  { key: 'date', label: '日期', type: 'date', width: 130 },
  { key: 'shipment_no', label: '集运单号', type: 'text', minWidth: 120, placeholder: '集运单号' },
  { key: 'intl_tracking_no', label: '国际运单号', type: 'text', minWidth: 120 },
  { key: 'recipient', label: '收货人', type: 'tag', field: 'recipient', width: 100 },
  { key: 'weight', label: '重量kg', type: 'decimal', width: 80 },
  { key: 'status', label: '状态', type: 'select', options: SHIPMENT_STATUS, width: 100, clearable: false },
  { key: 'price_cny', label: '运费（元）', type: 'decimal', format: 'cny', width: 110, placeholder: '实付运费' },
  { key: 'fx_rate', label: '汇率', type: 'decimal', width: 80, placeholder: '当天汇率' },
  { key: 'special_fee_jpy', label: '特殊费（円）', type: 'int', format: 'jpy', width: 110, placeholder: '关税/消费税' },
  { key: 'jpy_override', label: '覆盖（円）', type: 'int', format: 'jpy', width: 110, placeholder: '实付日元' },
  { key: 'jpy_settled', label: '结算（円）', format: 'jpy', readonly: true, width: 110 },
  { key: 'orders', label: '商品订单', readonly: true, minWidth: 160, expand: true },
]

const rows = ref([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = 30
const filters = reactive({ range: null, status: '', q: '' })
const unassignedOptions = ref([])

async function load() {
  loading.value = true
  try {
    const params = { limit: pageSize, offset: (page.value - 1) * pageSize }
    if (filters.range) { params.date_from = filters.range[0]; params.date_to = filters.range[1] }
    if (filters.status) params.status = filters.status
    if (filters.q) params.q = filters.q
    const res = await shipmentApi.list(params)
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
    const updated = await shipmentApi.update(row.id, { version: row.version, [key]: value })
    Object.assign(row, updated)
  } catch (e) {
    if (e.response?.status === 409) { ElMessage.warning(e.response?.data?.detail || '数据已变，已刷新'); load() }
  }
}

async function addRow(data = {}) {
  try {
    const created = await shipmentApi.create({ date: today(), status: '打包中', ...data })
    rows.value.unshift(created)
    total.value++
  } catch (_) { /* 拦截器已提示 */ }
}

async function delRow(row) {
  try {
    await ElMessageBox.confirm(`删除集运订单 ${row.shipment_no || row.id}？`, '确认', { type: 'warning' })
  } catch (_) { return }
  try {
    await shipmentApi.remove(row.id)
    ElMessage.success('已删除')
    if (rows.value.length === 1 && page.value > 1) page.value--   // 删掉本页最后一行 → 回上一页，避免停在空页
    load()                                                        // 重新拉取：分页/总数与后端同步
  } catch (_) { /* 拦截器已提示 */ }
}

function itemSummary(t) {
  if (!t.items || !t.items.length) return '—'
  return t.items.map((i) => `（${i.quantity}x）${i.name}`).join('，')
}
function tbSummary(row) {
  const list = row.orders || []
  if (!list.length) return '点击添加'
  return `${list.length} 单：${list.map((t) => t.order_no || ('#' + t.id)).join('，')}`
}
async function loadUnassigned() {
  try {
    const res = await ordersApi.list({ unassigned: true, limit: 200 })
    unassignedOptions.value = res.items
  } catch (_) { /* 拦截器已提示；避免 onMounted 里未捕获的 promise 拒绝 */ }
}
async function attach(shipmentRow, tbId) {
  if (!tbId) return
  try {
    const updated = await shipmentApi.attachOrder(shipmentRow.id, tbId)
    Object.assign(shipmentRow, updated)
    await loadUnassigned()
    ElMessage.success('已关联')
  } catch (_) { /* 拦截器已提示（含 422：已挂靠其他单） */ }
}
async function detach(shipmentRow, tbRow) {
  try {
    const updated = await shipmentApi.detachOrder(shipmentRow.id, tbRow.id)
    Object.assign(shipmentRow, updated)
    await loadUnassigned()
    ElMessage.success('已移除')
  } catch (_) { /* 拦截器已提示 */ }
}

onMounted(() => { load(); loadUnassigned() })
</script>

<style scoped>
.pager { margin-top: 12px; justify-content: flex-end; }
.ph { color: #5b6880; }
.expand { padding: 12px 20px; }
.ex-title { color: #9ba8bf; font-size: 13px; margin-bottom: 8px; }
.add-line { margin-top: 10px; display: flex; align-items: center; gap: 10px; }
.tb-pick { width: 320px; }
.tb-opt { display: flex; flex-direction: column; line-height: 1.25; }
.tb-meta { color: #7d8aa3; font-size: 11px; }
.small { font-size: 12px; }
</style>
