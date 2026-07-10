<template>
  <div class="gtn">
    <div v-if="$slots.toolbar" class="gtn-toolbar"><slot name="toolbar" /></div>

    <div class="gtn-scroll" v-loading="loading">
      <table class="gtn-table" :style="{ width: totalWidth + 'px' }">
        <colgroup>
          <col style="width: 56px" />
          <col v-if="hasActions" :style="{ width: actionsWidth + 'px' }" />
          <col v-if="expandable" style="width: 30px" />
          <col v-for="col in cols" :key="col.key" :style="{ width: (col.width || 160) + 'px' }" />
        </colgroup>

        <thead>
          <tr>
            <th class="gtn-th gtn-th-id">ID</th>
            <th v-if="hasActions" class="gtn-th gtn-th-act">操作</th>
            <th v-if="expandable" class="gtn-th"></th>
            <th v-for="col in cols" :key="col.key" class="gtn-th"
                :class="{ drag: !!tableName, dragging: dragKey === col.key, dragover: overKey === col.key }"
                :draggable="!!tableName"
                @dragstart="onDragStart($event, col)" @dragover.prevent="onDragOver(col)"
                @dragleave="onDragLeave(col)" @drop="onDrop(col)" @dragend="onDragEnd">
              <div class="gtn-th-inner">
                <span class="gtn-col-name">{{ col.label }}</span>
                <div v-if="tableName" class="gtn-resize" title="拖动改列宽"
                     @mousedown.stop.prevent="startResize($event, col)" @dragstart.prevent.stop />
              </div>
            </th>
          </tr>
        </thead>

        <tbody>
          <!-- 幽灵新建行：放最上，与「最新在上」一致；任意格输入即建行 -->
          <tr v-if="addable" class="gtn-new">
            <td class="gtn-td-id gtn-new-num" title="新建一行" @click="commitNew">
              <el-icon><component :is="hasNew ? Check : Plus" /></el-icon>
            </td>
            <td v-if="hasActions"></td>
            <td v-if="expandable"></td>
            <td v-for="col in cols" :key="'n-' + col.key" class="gtn-td">
              <GotionCell v-if="!col.readonly && !$slots['cell-' + col.key]"
                          :model-value="newRow[col.key]" :col="col" @change="(v) => onNew(col, v)" />
            </td>
          </tr>

          <template v-for="row in rows" :key="row.id">
            <tr class="gtn-row">
              <td class="gtn-td-id">
                <span class="num">{{ row.id }}</span>
                <el-icon class="del" title="删除此行" @click="$emit('delete', row)"><Delete /></el-icon>
              </td>
              <td v-if="hasActions" class="gtn-td gtn-td-act"><slot name="actions" :row="row" /></td>
              <td v-if="expandable" class="gtn-td-exp" @click="toggle(row.id)">
                <el-icon class="chev" :class="{ open: open.has(row.id) }"><ArrowRight /></el-icon>
              </td>
              <td v-for="col in cols" :key="col.key" class="gtn-td"
                  :class="{ 'gtn-td-clickexp': col.expand && expandable }"
                  @click="col.expand && expandable ? toggle(row.id) : null">
                <div v-if="$slots['cell-' + col.key]" class="gtn-slot"><slot :name="'cell-' + col.key" :row="row" /></div>
                <GotionCell v-else :model-value="row[col.key]" :col="col" @change="(v) => $emit('save', row, col.key, v)" />
              </td>
            </tr>
            <tr v-if="expandable && open.has(row.id)" class="gtn-exp-row">
              <td :colspan="colspan"><slot name="expand" :row="row" /></td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, useSlots, watch } from 'vue'
import { ArrowRight, Check, Delete, Plus } from '@element-plus/icons-vue'
import GotionCell from './GotionCell.vue'
import { layoutApi } from '@/api'

const props = defineProps({
  columns: { type: Array, required: true },
  rows: { type: Array, required: true },
  loading: Boolean,
  expandable: Boolean,
  addable: { type: Boolean, default: true },
  actionsWidth: { type: [Number, String], default: 72 },
  tableName: { type: String, default: '' },   // 有则启用列拖拽/拖宽 + 后端持久化
})
const emit = defineEmits(['save', 'add', 'delete'])
const slots = useSlots()

const open = reactive(new Set())
const newRow = reactive({})
const cols = ref([])
let savedLayout = []
let dirtyDuringLoad = false   // 用户在初始拉取期间改过布局？改过就别用 GET 结果覆盖

const hasActions = computed(() => !!slots.actions)
const colspan = computed(() => 1 + (props.expandable ? 1 : 0) + cols.value.length + (hasActions.value ? 1 : 0))
const totalWidth = computed(() =>
  56 + (props.expandable ? 30 : 0)
  + cols.value.reduce((s, c) => s + (c.width || 160), 0)
  + (hasActions.value ? Number(props.actionsWidth) : 0),
)
const hasNew = computed(() =>
  Object.keys(newRow).some((k) => { const v = newRow[k]; return v !== null && v !== undefined && v !== '' }),
)

// —— 用后端保存的顺序/宽度重排代码里定义的列 ——
function buildCols() {
  const base = props.columns
  if (!savedLayout.length) { cols.value = base.map((c) => ({ ...c })); return }
  const order = savedLayout.map((l) => l.key)
  const wmap = Object.fromEntries(savedLayout.map((l) => [l.key, l.width]))
  const byKey = Object.fromEntries(base.map((c) => [c.key, c]))
  const out = []
  order.forEach((k) => { if (byKey[k]) out.push({ ...byKey[k], width: wmap[k] ?? byKey[k].width }) })
  base.forEach((c) => { if (!order.includes(c.key)) out.push({ ...c }) })   // 新增列附加在后
  cols.value = out
}
watch(() => props.columns, buildCols)
onMounted(async () => {
  buildCols()
  if (props.tableName) {
    try {
      const r = await layoutApi.get(props.tableName)
      if (!dirtyDuringLoad) {          // 拉取期间用户已拖拽/拖宽过 → 保留用户改动，不覆盖
        savedLayout = r.columns || []
        buildCols()
      }
    } catch (_) { /* 忽略：用默认列 */ }
  }
})
function saveLayout() {
  if (!props.tableName) return
  dirtyDuringLoad = true
  savedLayout = cols.value.map((c) => ({ key: c.key, width: Math.round(c.width || 160) }))
  layoutApi.save(props.tableName, savedLayout).catch(() => {})
}

function toggle(id) { open.has(id) ? open.delete(id) : open.add(id) }

function onNew(col, value) {
  newRow[col.key] = value
  if (hasNew.value) commitNew()
}
function commitNew() {
  if (!hasNew.value) return
  const data = {}
  Object.keys(newRow).forEach((k) => {
    if (newRow[k] !== null && newRow[k] !== '') data[k] = newRow[k]
    delete newRow[k]
  })
  emit('add', data)
}

// —— 列拖拽换位 ——
const dragKey = ref(null)
const overKey = ref(null)
let resizing = false
function onDragStart(e, col) {
  if (resizing) { e.preventDefault(); return }
  dragKey.value = col.key
  e.dataTransfer.effectAllowed = 'move'
  e.dataTransfer.setData('text/plain', col.key)
}
function onDragOver(col) { if (dragKey.value && dragKey.value !== col.key) overKey.value = col.key }
function onDragLeave(col) { if (overKey.value === col.key) overKey.value = null }
function onDrop(target) {
  const from = cols.value.findIndex((c) => c.key === dragKey.value)
  const to = cols.value.findIndex((c) => c.key === target.key)
  if (from < 0 || to < 0 || from === to) return
  const arr = [...cols.value]
  const [moved] = arr.splice(from, 1)
  arr.splice(to, 0, moved)
  cols.value = arr
  saveLayout()
}
function onDragEnd() { dragKey.value = null; overKey.value = null }

// —— 列拖宽 ——
let rzCol = null
let rzX = 0
let rzW = 0
function startResize(e, col) {
  resizing = true
  rzCol = col
  rzX = e.clientX
  rzW = col.width || 160
  window.addEventListener('mousemove', onResize)
  window.addEventListener('mouseup', stopResize)
}
function onResize(e) {
  if (rzCol) rzCol.width = Math.max(60, rzW + e.clientX - rzX)
}
function stopResize() {
  if (rzCol) saveLayout()
  rzCol = null
  resizing = false
  window.removeEventListener('mousemove', onResize)
  window.removeEventListener('mouseup', stopResize)
}
</script>

<style scoped>
.gtn { display: flex; flex-direction: column; }
.gtn-toolbar { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.gtn-scroll { overflow: auto; border: 1px solid #28354a; border-radius: 8px; }
.gtn-table { border-collapse: collapse; font-size: 13px; color: #d6deea; table-layout: fixed; }

.gtn-th {
  background: #18233a; border-bottom: 2px solid #28354a; border-right: 1px solid #28354a;
  padding: 0; text-align: left; font-weight: 500; font-size: 12px; color: #c7d2e6;
  position: sticky; top: 0; z-index: 2; white-space: nowrap;
}
.gtn-th-act { text-align: center; padding: 8px 10px; }
.gtn-th-inner { display: flex; align-items: center; padding: 8px 10px; position: relative; }
.gtn-col-name { flex: 1; overflow: hidden; text-overflow: ellipsis; }
.gtn-th.drag { cursor: grab; }
.gtn-th.drag:active { cursor: grabbing; }
.gtn-th.dragging { opacity: 0.4; }
.gtn-th.dragover { box-shadow: inset 2px 0 0 #1890ff; background: #1d2a45; }
.gtn-resize { position: absolute; right: 0; top: 0; bottom: 0; width: 6px; cursor: col-resize; z-index: 3; }
.gtn-resize:hover { background: #3a4a6b; }

.gtn-row:hover td { background: #1b2942; }
.gtn-th-id { text-align: center; padding: 8px 6px; }
.gtn-td-id {
  text-align: center; color: #7a8aa3; font-size: 11px;
  border-bottom: 1px solid #202c44; border-right: 1px solid #28354a; position: relative;
}
.gtn-td-id .del { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); display: none; color: #f56c6c; cursor: pointer; }
.gtn-td-id:hover .num { opacity: 0; }
.gtn-td-id:hover .del { display: inline-flex; }
.gtn-td-exp { text-align: center; border-bottom: 1px solid #202c44; border-right: 1px solid #28354a; cursor: pointer; color: #7d8aa3; }
.gtn-td-exp .chev { transition: transform 0.15s; }
.gtn-td-exp .chev.open { transform: rotate(90deg); }
.gtn-td { height: 36px; padding: 0; border-bottom: 1px solid #202c44; border-right: 1px solid #28354a; max-width: 0; overflow: hidden; }
.gtn-td-act { overflow: visible; text-align: center; }
.gtn-td-clickexp { cursor: pointer; }
.gtn-slot { height: 36px; padding: 0 8px; display: flex; align-items: center; overflow: hidden; white-space: nowrap; }

.gtn-exp-row > td { background: #10192c; border-bottom: 1px solid #28354a; }
.gtn-new td { background: #10192c; border-bottom: 1px solid #202c44; border-right: 1px solid #28354a; }
.gtn-new-num { color: #5c6b85; cursor: pointer; }
.gtn-new-num:hover { color: #67c23a; background: rgba(103, 194, 58, 0.1); }
</style>
