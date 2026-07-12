<template>
  <div>
    <el-card>
      <NotionTable :columns="columns" :rows="rows" :loading="loading" table-name="misc"
                   @save="saveCell" @add="addRow" @delete="delRow">
        <template #toolbar>
          <el-date-picker v-model="filters.range" type="daterange" value-format="YYYY-MM-DD" class="flt-date"
                          start-placeholder="起" end-placeholder="止" @change="reload" />
          <el-input v-model="filters.q" placeholder="搜名称" clearable style="width: 150px" @change="reload" />
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
import { miscApi } from '@/api'
import NotionTable from '@/components/NotionTable.vue'

// 用本地时区（用户在日本=JST）的当天，而非 UTC；否则 JST 0~9 点新建会记成前一天
const today = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const columns = [
  { key: 'date', label: '日期', type: 'date', width: 140 },
  { key: 'name', label: '名称', type: 'text', minWidth: 150, placeholder: '名称' },
  { key: 'category', label: '分类', type: 'text', width: 120 },
  { key: 'price_cny', label: '人民币（元）', type: 'decimal', format: 'cny', width: 110, placeholder: '实付人民币' },
  { key: 'fx_rate', label: '汇率', type: 'decimal', width: 90, placeholder: '当天汇率' },
  { key: 'jpy_override', label: '覆盖（円）', type: 'int', format: 'jpy', width: 110, placeholder: '实付日元' },
  { key: 'jpy_settled', label: '结算（円）', format: 'jpy', readonly: true, width: 120 },
]

const rows = ref([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = 30
const filters = reactive({ range: null, q: '' })

async function load() {
  loading.value = true
  try {
    const params = { limit: pageSize, offset: (page.value - 1) * pageSize }
    if (filters.range) { params.date_from = filters.range[0]; params.date_to = filters.range[1] }
    if (filters.q) params.q = filters.q
    const res = await miscApi.list(params)
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
    const updated = await miscApi.update(row.id, { version: row.version, [key]: value })
    Object.assign(row, updated)
  } catch (e) {
    if (e.response?.status === 409) { ElMessage.warning(e.response?.data?.detail || '数据已变，已刷新'); load() }
  }
}

async function addRow(data = {}) {
  try {
    const created = await miscApi.create({ date: today(), name: '', ...data })
    rows.value.unshift(created)
    total.value++
  } catch (_) { /* 拦截器已提示 */ }
}

async function delRow(row) {
  try {
    await ElMessageBox.confirm(`删除杂项 ${row.name || row.id}？`, '确认', { type: 'warning' })
  } catch (_) { return }
  try {
    await miscApi.remove(row.id)
    rows.value = rows.value.filter((r) => r.id !== row.id)
    total.value--
    ElMessage.success('已删除')
  } catch (_) { /* 拦截器已提示 */ }
}

onMounted(load)
</script>

<style scoped>
.pager { margin-top: 12px; justify-content: flex-end; }
</style>
