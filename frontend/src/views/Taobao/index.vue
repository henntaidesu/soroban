<template>
  <div>
    <h2 class="page-title">淘宝订单</h2>

    <el-card>
      <NotionTable :columns="columns" :rows="rows" :loading="loading" expandable
                   table-name="taobao" @save="saveCell" @add="addRow" @delete="delRow">
        <template #toolbar>
          <el-date-picker v-model="filters.range" type="daterange" value-format="YYYY-MM-DD"
                          start-placeholder="起" end-placeholder="止" @change="reload" />
          <el-select v-model="filters.status" placeholder="状态" clearable style="width: 110px" @change="reload">
            <el-option v-for="s in TAOBAO_STATUS" :key="s" :label="s" :value="s" />
          </el-select>
          <el-input v-model="filters.taobao_account" placeholder="淘宝号" clearable style="width: 110px" @change="reload" />
          <el-input v-model="filters.express_no" placeholder="快递号" clearable style="width: 120px" @change="reload" />
          <el-input v-model="filters.q" placeholder="搜订单号" clearable style="width: 140px" @change="reload" />
        </template>

        <template #cell-shipment_order_id="{ row }">
          <el-select :model-value="row.shipment_order_id" clearable filterable placeholder="未集运"
                     size="small" class="jf-pick" @change="(v) => saveCell(row, 'shipment_order_id', v ?? null)">
            <el-option v-for="j in shipmentOptions" :key="j.id" :label="j.shipment_no || ('#' + j.id)" :value="j.id">
              <div class="jf-opt">
                <b>{{ j.shipment_no || ('#' + j.id) }}</b>
                <span class="jf-meta">{{ j.date }} · {{ j.status }} · 运费{{ fmtJPY(j.jpy_settled) }}</span>
              </div>
            </el-option>
          </el-select>
        </template>
        <template #cell-items="{ row }">
          <span :class="row.items && row.items.length ? '' : 'ph'">{{ itemSummary(row) }}</span>
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
            <div class="ex-hint">集运归属在上面「集运(点选)」列里改。</div>
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
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Plus } from '@element-plus/icons-vue'
import { shipmentApi, taobaoApi } from '@/api'
import { TAOBAO_STATUS } from '@/constants'
import { fmtJPY } from '@/utils/money'
import NotionTable from '@/components/NotionTable.vue'

const today = () => new Date().toISOString().slice(0, 10)

const columns = [
  { key: 'date', label: '日期', type: 'date', width: 130 },
  { key: 'order_no', label: '订单号', type: 'text', minWidth: 120, placeholder: '订单号' },
  { key: 'taobao_account', label: '淘宝号', type: 'text', width: 90 },
  { key: 'express_no', label: '快递号', type: 'text', width: 110 },
  { key: 'shop', label: '店铺', type: 'text', minWidth: 80 },
  { key: 'status', label: '状态', type: 'select', options: TAOBAO_STATUS, width: 90 },
  { key: 'price_cny', label: '人民币', type: 'decimal', format: 'cny', width: 95 },
  { key: 'fx_rate', label: '汇率', type: 'decimal', width: 75 },
  { key: 'jpy_override', label: '覆盖¥', type: 'int', format: 'jpy', width: 95, placeholder: '实付日元' },
  { key: 'jpy_settled', label: '结算¥', format: 'jpy', readonly: true, width: 100 },
  { key: 'shipment_order_id', label: '集运(点选)', readonly: true, width: 176 },
  { key: 'items', label: '物品', readonly: true, minWidth: 110, expand: true },
]

const rows = ref([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = 30
const filters = reactive({ range: null, status: '', taobao_account: '', express_no: '', q: '' })
const shipmentOptions = ref([])

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
    if (filters.range) { params.date_from = filters.range[0]; params.date_to = filters.range[1] }
    if (filters.status) params.status = filters.status
    if (filters.taobao_account) params.taobao_account = filters.taobao_account
    if (filters.express_no) params.express_no = filters.express_no
    if (filters.q) params.q = filters.q
    const res = await taobaoApi.list(params)
    rows.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}
function reload() { page.value = 1; load() }
function onPage(p) { page.value = p; load() }

async function loadShipment() {
  const res = await shipmentApi.list({ limit: 200 })
  shipmentOptions.value = res.items
}

async function saveCell(row, key, value) {
  try {
    const updated = await taobaoApi.update(row.id, { version: row.version, [key]: value })
    // 不覆盖 items：展开面板里可能有尚未点「保存物品」的编辑，普通单元格保存不应清掉它
    const { items, ...rest } = updated
    Object.assign(row, rest)
  } catch (e) {
    if (e.response?.status === 409) { ElMessage.warning(e.response?.data?.detail || '数据已变，已刷新'); load() }
  }
}

async function saveItems(row) {
  const items = (row.items || []).filter((it) => it.name && it.name.trim())
    .map((it) => ({ name: it.name.trim(), quantity: Number(it.quantity) || 1 }))
  try {
    const updated = await taobaoApi.update(row.id, { version: row.version, items })
    Object.assign(row, updated)
    ElMessage.success('物品已保存')
  } catch (e) {
    if (e.response?.status === 409) { ElMessage.warning('数据已变，已刷新'); load() }
  }
}

async function addRow(data = {}) {
  try {
    const created = await taobaoApi.create({ date: today(), status: '已付', ...data })
    rows.value.unshift(created)
    total.value++
  } catch (_) { /* 拦截器已提示 */ }
}

async function delRow(row) {
  try {
    await ElMessageBox.confirm(`删除订单 ${row.order_no || row.id}？`, '确认', { type: 'warning' })
  } catch (_) { return }
  try {
    await taobaoApi.remove(row.id)
    rows.value = rows.value.filter((r) => r.id !== row.id)
    total.value--
    ElMessage.success('已删除')
  } catch (_) { /* 拦截器已提示 */ }
}

onMounted(() => { loadShipment(); load() })
</script>

<style scoped>
.pager { margin-top: 12px; justify-content: flex-end; }
.ph { color: #5b6880; }
.expand { padding: 12px 20px; }
.ex-title { color: #9ba8bf; font-size: 13px; margin-bottom: 8px; }
.ex-hint { color: #7d8aa3; font-size: 12px; margin-top: 8px; }
.item-row { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; }
/* 集运点选：内嵌无边框，像格子里的选择 */
.jf-pick { width: 100%; }
.jf-pick :deep(.el-select__wrapper),
.jf-pick :deep(.el-input__wrapper) { box-shadow: none !important; background: transparent; }
.jf-opt { display: flex; flex-direction: column; line-height: 1.25; }
.jf-meta { color: #7d8aa3; font-size: 11px; }
</style>
