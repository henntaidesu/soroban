<template>
  <div>
    <el-card>
      <NotionTable :columns="columns" :rows="rows" :loading="loading" expandable :open-id="focusId"
                   table-name="taobao" @save="saveCell" @add="addRow" @delete="delRow">
        <template #toolbar>
          <el-upload ref="ocrUpload" class="ocr-up" drag :show-file-list="false" :auto-upload="false"
                     accept="image/*" :disabled="ocrLoading" :on-change="onOcrPick">
            <div class="ocr-drop" :class="{ busy: ocrLoading }">
              <el-icon class="ocr-ic"><Camera /></el-icon>
              <span>{{ ocrLoading ? '识别中…' : '点击或拖拽截图 OCR识别' }}</span>
            </div>
          </el-upload>
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
            <table class="item-tbl">
              <colgroup>
                <col class="c-name" />
                <col class="c-qty" />
                <col class="c-act" />
              </colgroup>
              <tbody>
                <tr v-for="(it, i) in (row.items || [])" :key="i">
                  <td><el-input v-model="it.name" size="small" placeholder="物品名" @change="saveItems(row)" /></td>
                  <td><el-input-number v-model="it.quantity" :min="1" :controls="false" size="small" @change="saveItems(row)" /></td>
                  <td class="c-act"><el-button link type="danger" :icon="Delete" tabindex="-1" @click="removeItem(row, i)" /></td>
                </tr>
                <!-- 末尾草稿行：输入名称并失焦/回车即成为新物品并自动写库，随后又出现空行可继续录入 -->
                <tr v-if="drafts[row.id]" class="draft-row">
                  <td><el-input v-model="drafts[row.id].name" size="small" placeholder="+ 新物品名，输入后自动保存"
                                @change="commitDraft(row)" @keyup.enter="commitDraft(row)" /></td>
                  <td><el-input-number v-model="drafts[row.id].quantity" :min="1" :controls="false" size="small" /></td>
                  <td class="c-act"></td>
                </tr>
              </tbody>
            </table>
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
import { Camera, Check, Delete } from '@element-plus/icons-vue'
import { shipmentApi, taobaoApi } from '@/api'
import { ORDER_SOURCES, TAOBAO_STATUS, statusStyle } from '@/constants'
import { fmtJPY } from '@/utils/money'
import NotionTable from '@/components/NotionTable.vue'

// 用本地时区（用户在日本=JST）的当天，而非 UTC；否则 JST 0~9 点新建会记成前一天
const today = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// 默认列顺序 + 统一列宽（≈ 刚好显示日期，取整多留一点 = 110）；用户可拖动改序/改宽，改动持久化
const COL_W = 110
const columns = [
  { key: 'date', label: '下单日期', type: 'date', width: COL_W },
  { key: 'taobao_account', label: '淘宝号', type: 'tag', field: 'taobao_account', width: COL_W },
  { key: 'platform', label: '来源', type: 'select', options: ORDER_SOURCES, width: COL_W, placeholder: '来源' },
  { key: 'shop', label: '商品', type: 'text', long: true, width: COL_W },
  { key: 'items', label: '物品', readonly: true, width: COL_W, expand: true },
  { key: 'status', label: '状态', type: 'select', options: TAOBAO_STATUS, width: COL_W, clearable: false },
  { key: 'shipment_order_id', label: '集运订单', readonly: true, width: COL_W, placeholder: '选择' },
  { key: 'jpy_settled', label: '结算（円）', format: 'jpy', readonly: true, width: COL_W },
  { key: 'jpy_override', label: '覆盖（円）', type: 'int', format: 'jpy', width: COL_W, placeholder: '实付日元' },
  { key: 'price_cny', label: '人民币（元）', type: 'decimal', format: 'cny', width: COL_W, placeholder: '实付人民币' },
  { key: 'fx_rate', label: '汇率', type: 'decimal', width: COL_W, placeholder: '当天汇率' },
  { key: 'express_company', label: '快递公司', type: 'text', width: COL_W, placeholder: '快递公司' },
  { key: 'express_no', label: '快递号', type: 'text', width: COL_W, placeholder: '快递号' },
  { key: 'order_no', label: '订单号', type: 'text', width: COL_W, placeholder: '订单号' },
]

const rows = ref([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = 30
const focusId = ref(null)   // 跳转定位的订单 id（?focus=）
const filters = reactive({ range: null, status: '', taobao_account: '', express_no: '', q: '' })
const shipmentOptions = ref([])
const drafts = reactive({})   // { rowId: { name, quantity } } 每行末尾的「新物品」草稿输入
function ensureDraft(id) { if (!drafts[id]) drafts[id] = { name: '', quantity: 1 } }

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
  return row.items.map((it) => `（${it.quantity}x）${it.name}`).join('，')
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
    rows.value.forEach((r) => ensureDraft(r.id))
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
    Object.assign(row, updated)   // 自动保存：静默写库，不弹提示
  } catch (e) {
    if (e.response?.status === 409) { ElMessage.warning('数据已变，已刷新'); load() }
  }
}

// 删除某物品：二次确认后再移除并写库
async function removeItem(row, i) {
  const it = row.items?.[i]
  try {
    await ElMessageBox.confirm(`删除物品「${it?.name || '未命名'}」？`, '确认', { type: 'warning' })
  } catch (_) { return }
  row.items.splice(i, 1)
  saveItems(row)
}

// 末尾草稿录入完成：转为正式物品、清空草稿、自动写库；随后草稿行再次出现可继续录入
async function commitDraft(row) {
  const d = drafts[row.id]
  if (!d || !d.name || !d.name.trim()) return
  ensureItems(row).push({ name: d.name.trim(), quantity: Number(d.quantity) || 1 })
  drafts[row.id] = { name: '', quantity: 1 }
  await saveItems(row)
}

// OCR 识别订单截图：抽取快递公司/快递号/订单号/成交价，识别到就新建一行并回填
const ocrLoading = ref(false)
const ocrUpload = ref(null)
async function onOcrPick(uploadFile) {
  const file = uploadFile?.raw
  if (!file || ocrLoading.value) return
  if (file.type && !file.type.startsWith('image/')) {   // 拖拽不受 accept 约束，挡掉非图片
    ElMessage.warning('请拖入图片文件')
    ocrUpload.value?.clearFiles?.()
    return
  }
  ocrLoading.value = true
  try {
    const res = await taobaoApi.ocr(file)
    const data = {}
    if (res.platform) data.platform = res.platform
    if (res.express_company) data.express_company = res.express_company
    if (res.express_no) data.express_no = res.express_no
    if (res.order_no) data.order_no = res.order_no
    if (res.price_cny != null && res.price_cny !== '') data.price_cny = res.price_cny
    if (!Object.keys(data).length) {
      ElMessage.warning('未能从截图识别到快递/订单信息，请手动填写')
      return
    }
    await addRow(data)
    const parts = []
    if (data.platform) parts.push(`来源 ${data.platform}`)
    if (data.express_company) parts.push(`快递 ${data.express_company}`)
    if (data.express_no) parts.push(`快递号 ${data.express_no}`)
    if (data.order_no) parts.push(`订单号 ${data.order_no}`)
    if (data.price_cny) parts.push(`成交价 ¥${data.price_cny}`)
    ElMessage.success(`已识别并新建订单 · ${parts.join(' · ')}`)
  } catch (_) {
    // 依赖未装(503)/图片错误(400) 等由 http 拦截器统一提示
  } finally {
    ocrLoading.value = false
    ocrUpload.value?.clearFiles?.()   // 清掉内部文件列表，便于重复选同一张图
  }
}

async function addRow(data = {}) {
  try {
    // status 不写死：后端 TaobaoBase 默认「待发货」，避免枚举改名后前端残留非法值（曾用'已付'→422）
    const created = await taobaoApi.create({ date: today(), ...data })
    rows.value.unshift(created)
    ensureDraft(created.id)
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
    delete drafts[row.id]
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
/* OCR 上传：紧凑拖拽区，内联进工具栏（覆盖 el-upload drag 默认的大块留白） */
.ocr-up { display: inline-flex; }
.ocr-up :deep(.el-upload) { display: inline-flex; }
.ocr-up :deep(.el-upload-dragger) {
  padding: 0 14px; height: 32px; display: inline-flex; align-items: center;
  border-radius: 4px; border-style: dashed; border-color: #3a4a6b; background: transparent;
}
.ocr-up :deep(.el-upload-dragger:hover),
.ocr-up :deep(.el-upload-dragger.is-dragover) { border-color: #409eff; background: rgba(64, 158, 255, 0.08); }
.ocr-drop { display: inline-flex; align-items: center; gap: 6px; color: #7f9cff; font-size: 13px; white-space: nowrap; }
.ocr-drop.busy { color: #7d8aa3; }
.ocr-ic { font-size: 15px; }
.focus-chip { font-weight: 500; }
.focus-empty { color: #9ba8bf; font-size: 13px; padding: 16px; text-align: center; }
.ph { color: #5b6880; }
.expand { padding: 12px 20px; }
/* 二级子表格：视觉与一级列表(NotionTable)一致——同样的边框、行高与悬停；无表头 */
.item-tbl { border-collapse: collapse; font-size: 13px; color: #d6deea; table-layout: fixed; }
.item-tbl col.c-name { width: 260px; }
.item-tbl col.c-qty { width: 110px; }
.item-tbl col.c-act { width: 64px; }
.item-tbl td { height: 36px; padding: 0; border-bottom: 1px solid #202c44; border-right: 1px solid #28354a; }
.item-tbl tbody tr:hover td { background: #1b2942; }
.item-tbl td.c-act { text-align: center; }
/* 单元格内输入做成无边框，贴合一级列表的扁平格子观感 */
.item-tbl :deep(.el-input__wrapper),
.item-tbl :deep(.el-input-number .el-input__wrapper) {
  box-shadow: none !important; background: transparent; padding: 0 10px; height: 36px;
}
.item-tbl :deep(.el-input-number) { width: 100%; line-height: normal; }
.item-tbl :deep(.el-input-number .el-input__inner) { text-align: left; }
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
