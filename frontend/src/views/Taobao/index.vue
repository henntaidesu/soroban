<template>
  <div>
    <el-card>
      <NotionTable :columns="columns" :rows="rows" :loading="loading" expandable :open-id="focusId"
                   table-name="taobao" @save="saveCell" @add="addRow" @delete="delRow">
        <template #toolbar>
          <el-tag v-if="focusId" type="warning" closable disable-transitions class="focus-chip" @close="clearFocus">
            定位订单 #{{ focusId }} · 点 × 看全部
          </el-tag>
          <el-date-picker v-model="filters.range" type="daterange" value-format="YYYY-MM-DD" class="flt-date"
                          start-placeholder="起" end-placeholder="止" @change="reload" />
          <el-select v-model="filters.status" placeholder="状态" clearable style="width: 110px" @change="reload">
            <el-option v-for="s in TAOBAO_STATUS" :key="s" :label="s" :value="s" />
          </el-select>
          <el-input v-model="filters.taobao_account" placeholder="淘宝号" clearable style="width: 110px" @change="reload" />
          <el-input v-model="filters.express_no" placeholder="快递号" clearable style="width: 120px" @change="reload" />
          <el-input v-model="filters.q" placeholder="搜订单号" clearable style="width: 140px" @change="reload" />
        </template>

        <template #cell-shipment_order_id="{ row }">
          <el-select :model-value="row.shipment_order_id" filterable placeholder="未集运"
                     size="small" class="ship-pick" popper-class="ship-pop"
                     @change="(v) => onPickShipment(row, v)">
            <template #label="{ value }">
              <span class="ship-sel">
                <b>{{ shipNo(value) }}</b>
                <el-tag v-if="shipById(value)" size="small" :style="statusStyle(shipById(value).status)">{{ shipById(value).status }}</el-tag>
              </span>
            </template>
            <!-- 清除固定在列表最上（集运单可能很多）；无归属时不显示 -->
            <el-option v-if="row.shipment_order_id" :value="-1" label="清除">
              <div class="ship-clear">清除（取消集运）</div>
            </el-option>
            <el-option v-for="j in sortedShipments" :key="j.id" :label="j.shipment_no || ('#' + j.id)" :value="j.id">
              <div class="ship-opt">
                <div class="ship-opt-top">
                  <b>{{ j.shipment_no || ('#' + j.id) }}</b>
                  <el-tag size="small" :style="statusStyle(j.status)">{{ j.status }}</el-tag>
                  <el-icon v-if="j.id === row.shipment_order_id" class="ship-ck"><Check /></el-icon>
                </div>
                <span class="ship-meta">{{ j.date }} · 运费 {{ j.jpy_settled != null ? fmtJPY(j.jpy_settled) : '待定' }}</span>
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

      <div v-if="focusId && !loading && !total" class="focus-empty">
        未找到该订单（可能已删除）。<el-link type="primary" @click="clearFocus">显示全部</el-link>
      </div>

      <el-pagination class="pager" layout="prev, pager, next, total" :total="total"
                     :page-size="pageSize" :current-page="page" @current-change="onPage" />
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, Delete, Plus } from '@element-plus/icons-vue'
import { shipmentApi, taobaoApi } from '@/api'
import { TAOBAO_STATUS, statusStyle } from '@/constants'
import { fmtJPY } from '@/utils/money'
import NotionTable from '@/components/NotionTable.vue'

// 用本地时区（用户在日本=JST）的当天，而非 UTC；否则 JST 0~9 点新建会记成前一天
const today = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const columns = [
  { key: 'date', label: '日期', type: 'date', width: 130 },
  { key: 'order_no', label: '订单号', type: 'text', minWidth: 120, placeholder: '订单号' },
  { key: 'taobao_account', label: '淘宝号', type: 'tag', field: 'taobao_account', width: 110 },
  { key: 'express_no', label: '快递号', type: 'text', width: 110, placeholder: '快递号' },
  { key: 'shop', label: '商品', type: 'text', minWidth: 80 },
  { key: 'status', label: '状态', type: 'select', options: TAOBAO_STATUS, width: 90, clearable: false },
  { key: 'price_cny', label: '人民币（元）', type: 'decimal', format: 'cny', width: 110, placeholder: '实付人民币' },
  { key: 'fx_rate', label: '汇率', type: 'decimal', width: 80, placeholder: '当天汇率' },
  { key: 'jpy_override', label: '覆盖（円）', type: 'int', format: 'jpy', width: 110, placeholder: '实付日元' },
  { key: 'jpy_settled', label: '结算（円）', format: 'jpy', readonly: true, width: 110 },
  { key: 'shipment_order_id', label: '集运订单', readonly: true, width: 176, placeholder: '选择' },
  { key: 'items', label: '物品', readonly: true, minWidth: 110, expand: true },
]

const rows = ref([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = 30
const focusId = ref(null)   // 跳转定位的订单 id（?focus=）
const filters = reactive({ range: null, status: '', taobao_account: '', express_no: '', q: '' })
const shipmentOptions = ref([])

function shipById(id) { return shipmentOptions.value.find((j) => j.id === id) }
function shipNo(id) { const j = shipById(id); return j ? (j.shipment_no || ('#' + id)) : ('#' + id) }
// 打包中的集运单永远置顶（最常挂新订单）；其余保持原顺序（日期倒序）。sort 稳定，同组不乱。
const sortedShipments = computed(() =>
  [...shipmentOptions.value].sort((a, b) => (b.status === '打包中' ? 1 : 0) - (a.status === '打包中' ? 1 : 0)),
)
function onPickShipment(row, v) {   // -1 = 列表里的「清除」项；其余为集运单 id
  saveCell(row, 'shipment_order_id', v === -1 ? null : (v ?? null))
}

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
    if (focusId.value) params.id = focusId.value          // 跳转定位：隔离显示该单
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
    // status 不写死：后端 TaobaoBase 默认「待发货」，避免枚举改名后前端残留非法值（曾用'已付'→422）
    const created = await taobaoApi.create({ date: today(), ...data })
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

// 集运页点订单号跳转过来：?focus=<id> → 隔离显示该单并自动展开；重复跳转（改 query）也响应。
// immediate 负责首次加载，故 onMounted 不再重复调 load。
const route = useRoute()
const router = useRouter()
watch(() => route.query.focus, (v) => {
  focusId.value = (v !== undefined && v !== null && v !== '') ? Number(v) : null
  page.value = 1
  load()
}, { immediate: true })
function clearFocus() { router.replace({ path: '/taobao', query: {} }) }

onMounted(() => { loadShipment() })
</script>

<style scoped>
.pager { margin-top: 12px; justify-content: flex-end; }
.focus-chip { font-weight: 500; }
.focus-empty { color: #9ba8bf; font-size: 13px; padding: 16px; text-align: center; }
.ph { color: #5b6880; }
.expand { padding: 12px 20px; }
.ex-title { color: #9ba8bf; font-size: 13px; margin-bottom: 8px; }
.ex-hint { color: #7d8aa3; font-size: 12px; margin-top: 8px; }
.item-row { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; }
/* 集运点选：内嵌无边框，像格子里的选择 */
.ship-pick { width: 100%; }
.ship-pick :deep(.el-select__wrapper),
.ship-pick :deep(.el-input__wrapper) { box-shadow: none !important; background: transparent; }
/* 隐藏下拉箭头/清除叉，避免误触；清除改放到下拉列表里 */
.ship-pick :deep(.el-select__suffix) { display: none; }
.ship-clear { color: #9ba8bf; font-size: 12px; }
.ship-opt { display: flex; flex-direction: column; gap: 3px; line-height: 1.3; }
.ship-opt-top { display: flex; align-items: center; gap: 8px; }
.ship-meta { color: #7d8aa3; font-size: 11px; }
.ship-ck { margin-left: auto; color: #67c23a; font-size: 14px; }
/* 单元格里显示所选集运单：单号 + 状态标签 */
.ship-sel { display: inline-flex; align-items: center; gap: 6px; min-width: 0; }
.ship-sel b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
