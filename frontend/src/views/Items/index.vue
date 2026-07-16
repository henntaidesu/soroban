<template>
  <div>
    <div class="bar">
      <span class="hint">所有订单的物品拉平成一张表（对接的最小单位）。列可拖动换位/拖宽。物品编辑请到「商品订单」页展开面板里做。</span>
    </div>

    <el-card>
      <NotionTable :columns="columns" :rows="rows" :loading="loading"
                   table-name="items" hide-id :addable="false" :deletable="false" @reload="load">
        <template #toolbar>
          <el-select v-model="filters.status" placeholder="全部状态" clearable style="width: 120px" @change="reload">
            <el-option v-for="s in TAOBAO_STATUS" :key="s" :label="s" :value="s" />
          </el-select>
          <el-select v-model="filters.platform" placeholder="全部来源" clearable style="width: 110px" @change="reload">
            <el-option v-for="p in ORDER_SOURCES" :key="p" :label="p" :value="p" />
          </el-select>
          <el-input v-model="filters.taobao_account" placeholder="淘宝账号" clearable style="width: 120px" @change="reload" />
          <el-input v-model="filters.q" placeholder="搜物品/订单号/商品" clearable style="width: 180px" @change="reload" />
        </template>

        <!-- 彩色标签（只读），配色与订单列表一致：账号用持久化色序、来源/状态用语义色 -->
        <template #cell-taobao_account="{ row }">
          <el-tag v-if="row.taobao_account" size="small" :style="tagStyleAt(acctColor[row.taobao_account] ?? -1, row.taobao_account)">{{ row.taobao_account }}</el-tag>
          <span v-else class="ph">—</span>
        </template>
        <template #cell-platform="{ row }">
          <el-tag v-if="row.platform" size="small" :style="statusStyle(row.platform)">{{ row.platform }}</el-tag>
          <span v-else class="ph">—</span>
        </template>
        <template #cell-status="{ row }">
          <el-tag size="small" :style="statusStyle(row.status)">{{ row.status }}</el-tag>
        </template>
        <!-- 灰显=物品名与商品标题相同（无独立物品详情） -->
        <template #cell-name="{ row }">
          <span :class="{ 'auto-txt': isTitleItem(row) }" :title="isTitleItem(row) ? '物品名与商品标题相同（无独立物品详情）' : ''">{{ row.name }}</span>
        </template>
      </NotionTable>

      <el-pagination class="pager" layout="prev, pager, next, total" :total="total"
                     :page-size="pageSize" :current-page="page" @current-change="onPage" />
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { itemsApi, tagsApi } from '@/api'
import { ORDER_SOURCES, TAOBAO_STATUS, statusStyle, tagStyleAt } from '@/constants'
import NotionTable from '@/components/NotionTable.vue'

// 默认列顺序 + 宽度；用户可拖动改序/改宽，持久化到后端（table-name="items"）
const columns = [
  { key: 'date', label: '下单日期', readonly: true, width: 100 },
  { key: 'taobao_account', label: '账号', readonly: true, width: 100 },
  { key: 'platform', label: '来源', readonly: true, width: 80 },
  { key: 'shop', label: '商品', readonly: true, width: 130 },
  { key: 'name', label: '物品名', readonly: true, width: 180 },
  { key: 'quantity', label: '数量', readonly: true, width: 64 },
  { key: 'price_cny', label: '单价（元）', format: 'cny', readonly: true, width: 100 },
  { key: 'amount_cny', label: '金额（元）', format: 'cny', readonly: true, width: 100 },
  { key: 'status', label: '状态', readonly: true, width: 84 },
  { key: 'order_no', label: '订单号', readonly: true, width: 130 },
  { key: 'express_no', label: '快递号', readonly: true, width: 110 },
]

const rows = ref([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = 30
const filters = reactive({ status: '', platform: '', taobao_account: '', q: '' })

// 账号标签的持久化配色（与其它页同一套色序，保证同一账号处处同色）
const acctColor = reactive({})
async function loadAcctColors() {
  try {
    const tags = await tagsApi.list('taobao_account')
    tags.forEach((t) => { acctColor[t.value] = t.color })
  } catch (_) { /* 拦截器已提示 */ }
}

async function load() {
  loading.value = true
  try {
    const params = { limit: pageSize, offset: (page.value - 1) * pageSize }
    if (filters.status) params.status = filters.status
    if (filters.platform) params.platform = filters.platform
    if (filters.taobao_account) params.taobao_account = filters.taobao_account
    if (filters.q) params.q = filters.q
    const res = await itemsApi.list(params)
    rows.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}
function reload() { page.value = 1; load() }
function onPage(p) { page.value = p; load() }

// 灰显 = 物品名与商品标题相同（无独立物品详情）
function isTitleItem(row) {
  return !!row.name && (row.name || '').trim() === (row.shop || '').trim()
}

onMounted(() => { loadAcctColors(); load() })
</script>

<style scoped>
.bar { margin-bottom: 10px; }
.hint { color: #7d8aa3; font-size: 12px; }
.pager { margin-top: 12px; justify-content: flex-end; }
.ph { color: #5b6880; }
.auto-txt { color: #6b7488; font-style: italic; }
</style>
