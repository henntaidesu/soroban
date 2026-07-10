<template>
  <div>
    <h2 class="page-title">看板</h2>

    <el-row :gutter="16" v-loading="loading">
      <el-col :xs="12" :sm="12" :md="6" v-for="c in cards" :key="c.label">
        <div class="stat" :style="{ borderTopColor: c.color }">
          <div class="stat-label">{{ c.label }}</div>
          <div class="stat-value">{{ fmtJPY(c.value) }}</div>
          <div class="stat-sub">{{ c.sub }}</div>
        </div>
      </el-col>
    </el-row>

    <el-card style="margin-top: 16px">
      <template #header>按月支出（结算日元）</template>
      <el-table :data="data.by_month" size="small" empty-text="暂无数据">
        <el-table-column prop="month" label="月份" />
        <el-table-column label="金额">
          <template #default="{ row }">{{ fmtJPY(row.jpy) }}</template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { dashboardApi } from '@/api'
import { fmtJPY } from '@/utils/money'

const loading = ref(false)
const data = reactive({
  total_jpy: 0, taobao_jpy: 0, junfeng_jpy: 0, misc_jpy: 0,
  taobao_count: 0, junfeng_count: 0, misc_count: 0, by_month: [], fx_rate: null,
})

const cards = computed(() => [
  { label: '总支出', value: data.total_jpy, color: '#1890ff', sub: `汇率 1元≈${data.fx_rate ?? '—'}円` },
  { label: '淘宝（含快递）', value: data.taobao_jpy, color: '#67C23A', sub: `${data.taobao_count} 单` },
  { label: '君丰运费', value: data.junfeng_jpy, color: '#E6A23C', sub: `${data.junfeng_count} 单` },
  { label: '杂项', value: data.misc_jpy, color: '#F56C6C', sub: `${data.misc_count} 项` },
])

async function load() {
  loading.value = true
  try {
    Object.assign(data, await dashboardApi.get())
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<style scoped>
.stat {
  background: #131c2f; border: 1px solid #28354a; border-top: 3px solid #1890ff;
  border-radius: 8px; padding: 16px; margin-bottom: 16px;
}
.stat-label { color: #9ba8bf; font-size: 13px; }
.stat-value { color: #e6edf7; font-size: 26px; font-weight: 700; margin: 6px 0; }
.stat-sub { color: #7d8aa3; font-size: 12px; }
</style>
