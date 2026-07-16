<template>
  <div>
    <div class="bar">
      <span class="hint">一个账号昵称下的所有订单都放这里（一单可多物），逐单点「导入」才进入账本。（将来爬虫自动灌入）</span>
    </div>

    <el-card>
      <NotionTable :columns="columns" :rows="rows" :loading="loading" expandable
                   table-name="staging" :actions-width="128" @save="saveCell" @add="addRow" @delete="doDelete" @reload="load">
        <template #toolbar>
          <el-select v-model="filters.status" placeholder="全部状态" clearable style="width: 130px" @change="reload">
            <el-option v-for="s in STAGING_STATUS" :key="s" :label="s" :value="s" />
          </el-select>
          <el-input v-model="filters.taobao_account" placeholder="账号昵称" clearable style="width: 130px" @change="reload" />
          <el-input v-model="filters.q" placeholder="搜订单号/商品" clearable style="width: 160px" @change="reload" />
        </template>

        <template #cell-scraped_at="{ row }">
          <span :class="row.scraped_at ? '' : 'ph'">{{ fmtDate(row.scraped_at) }}</span>
        </template>
        <template #cell-items="{ row }">
          <span :class="{ ph: !(row.items && row.items.length), 'auto-txt': allTitleItems(row) }">{{ itemSummary(row) }}</span>
        </template>
        <template #cell-status="{ row }">
          <el-tag :style="stagingStyle(row.status)" size="small">{{ row.status }}</el-tag>
        </template>

        <template #expand="{ row }">
          <div class="expand">
            <div class="ex-title">物品明细（一单多物）· 单价×数量汇总为订单价</div>
            <div v-for="(it, i) in row.items" :key="i" class="item-row" :class="{ 'item-auto': isTitleItem(row, it) }"
                 :title="isTitleItem(row, it) ? '物品名与商品标题相同（无独立物品详情）；改成真实物品名即正常' : ''">
              <el-input v-model="it.name" size="small" placeholder="物品名" style="width: 180px" @change="it.auto = false" />
              <el-input-number v-model="it.quantity" :min="1" :controls="false" size="small" style="width: 80px" @change="it.auto = false" />
              <el-input-number v-model="it.price_cny" :min="0" :precision="2" :controls="false" size="small"
                               style="width: 110px" placeholder="单价" @change="it.auto = false" />
              <el-button link type="danger" :icon="Delete" @click="row.items.splice(i, 1)" />
            </div>
            <div>
              <el-button size="small" :icon="Plus" @click="ensureItems(row).push({ name: '', quantity: 1, price_cny: null, auto: false })">加物品</el-button>
              <el-button size="small" type="primary" @click="saveItems(row)">保存物品</el-button>
            </div>
            <div class="postage-row">
              <span class="postage-lb">邮费（元）</span>
              <el-input-number v-model="row.postage_cny" :min="0" :precision="2" :controls="false" size="small"
                               placeholder="包邮" style="width: 130px" @change="savePostage(row)" />
              <span class="postage-hint">不填 = 包邮（订单价 = Σ单价×数量 + 邮费）</span>
            </div>
          </div>
        </template>

        <template #actions="{ row }">
          <template v-if="row.imported_taobao_order_id">
            <el-tag :style="stagingStyle('已导入')" size="small">已导入 #{{ row.imported_taobao_order_id }}</el-tag>
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
import { STAGING_STATUS, TAOBAO_STATUS, stagingStyle } from '@/constants'
import NotionTable from '@/components/NotionTable.vue'

// 默认列顺序 + 统一列宽（≈ 刚好显示日期，取整多留一点 = 110）；用户可拖动改序/改宽，改动持久化
const COL_W = 110
const columns = [
  { key: 'order_date', label: '下单日期', type: 'date', width: COL_W },
  { key: 'taobao_account', label: '账号昵称', type: 'tag', field: 'taobao_account', width: COL_W },
  { key: 'platform', label: '来源', type: 'tag', field: 'platform', width: COL_W, placeholder: '来源' },
  { key: 'shop', label: '商品', type: 'text', long: true, width: COL_W },   // 标题长：点开弹宽框看全
  { key: 'price_cny', label: '人民币（元）', format: 'cny', readonly: true, width: COL_W },   // 由物品单价×数量派生
  { key: 'order_status', label: '订单状态', type: 'select', options: TAOBAO_STATUS, width: COL_W },
  { key: 'items', label: '物品', readonly: true, width: COL_W, expand: true },
  { key: 'order_no', label: '订单号', type: 'text', width: COL_W, placeholder: '订单号' },
  { key: 'express_no', label: '快递号', type: 'text', width: COL_W, placeholder: '快递号' },
  { key: 'scraped_at', label: '入库日期', readonly: true, width: COL_W },   // 写进库的日期，方便按批次筛选
  { key: 'fx_rate', label: '汇率', type: 'decimal', width: COL_W, placeholder: '当天汇率' },
  { key: 'status', label: '导入状态', readonly: true, width: COL_W },
]

const rows = ref([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = 30
const filters = reactive({ status: '', taobao_account: '', q: '' })

function itemSummary(row) {
  if (!row.items || !row.items.length) return '—'
  return row.items.map((it) => `（${it.quantity}x）${it.name}`).join('，')
}
// 灰显 = 物品名与商品标题相同（无独立物品详情）；有真实物品名即正常
function isTitleItem(row, it) {
  return !!it.name && (it.name || '').trim() === (row.shop || '').trim()
}
// 列表「物品」格：全是标题占位（自动生成）时整格灰显
function allTitleItems(row) {
  return !!(row.items && row.items.length) && row.items.every((it) => isTitleItem(row, it))
}
function fmtDate(s) {                         // 入库日期：后端存 UTC(naive)，补 Z 后按本地(JST)显示为 YYYY-MM-DD
  if (!s) return '—'
  const d = new Date(/[Z+]/.test(s) ? s : s + 'Z')
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
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
    const updated = await stagingApi.update(row.id, { version: row.version, [key]: value })
    const { items, ...rest } = updated       // 不覆盖展开面板里未保存的物品编辑
    Object.assign(row, rest)
  } catch (e) {
    if (e.response?.status === 409) {
      ElMessage.warning(e.response?.data?.detail || '数据已变，已刷新')
      load()   // 冲突：刷新回退到服务器状态
    }
    // 非 409：拦截器已提示，单元格自动显示旧值，无需整页重拉
  }
}

async function saveItems(row) {
  const items = (row.items || []).filter((it) => it.name && it.name.trim())
    .map((it) => ({ name: it.name.trim(), quantity: Number(it.quantity) || 1,
                    price_cny: (it.price_cny === '' || it.price_cny == null) ? null : Number(it.price_cny),
                    auto: !!it.auto }))
  try {
    const updated = await stagingApi.update(row.id, { version: row.version, items })
    Object.assign(row, updated)
    ElMessage.success('物品已保存')
  } catch (e) {
    // 仅 409（数据已变）才整表刷新；其它错误交拦截器提示，保留本地未保存编辑
    if (e.response?.status === 409) { ElMessage.warning(e.response?.data?.detail || '数据已变，已刷新'); load() }
  }
}

// 邮费改动：写库并让暂存价随之重算（不填=包邮）。不覆盖未保存的物品编辑
async function savePostage(row) {
  const postage = (row.postage_cny === '' || row.postage_cny == null) ? null : Number(row.postage_cny)
  try {
    const updated = await stagingApi.update(row.id, { version: row.version, postage_cny: postage })
    const { items, ...rest } = updated
    Object.assign(row, rest)
  } catch (e) {
    if (e.response?.status === 409) { ElMessage.warning(e.response?.data?.detail || '数据已变，已刷新'); load() }
  }
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
    ElMessage.success('已导入到商品订单账本')
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
.bar { margin-bottom: 10px; }
.hint { color: #7d8aa3; font-size: 12px; }
.pager { margin-top: 12px; justify-content: flex-end; }
.ph { color: #5b6880; }
.auto-txt { color: #6b7488; font-style: italic; }   /* 列表「物品」格：自动生成(名=标题)时灰显 */
.expand { padding: 12px 20px; }
.ex-title { color: #9ba8bf; font-size: 13px; margin-bottom: 8px; }
.item-row { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; }
/* 灰显：系统自动生成/自动定价的物品（编辑即去灰） */
.item-row.item-auto :deep(.el-input__inner) { color: #6b7488; font-style: italic; }
.postage-row { display: flex; align-items: center; gap: 10px; margin-top: 10px; }
.postage-lb { color: #9ba8bf; font-size: 13px; }
.postage-hint { color: #7d8aa3; font-size: 12px; }
</style>
