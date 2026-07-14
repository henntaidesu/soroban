<template>
  <!-- 只读展示（派生金额等） -->
  <div v-if="col.readonly" class="gtn-disp">
    <span v-if="disp !== null" :class="col.format ? 'derived' : ''">{{ disp }}</span>
    <span v-else class="ph">{{ emptyText }}</span>
  </div>

  <!-- select：tag + 弹出选项 -->
  <el-popover v-else-if="col.type === 'select'" :visible="editing" :width="180" :offset="4"
              placement="bottom-start" @update:visible="(v) => !v && (editing = false)">
    <template #reference>
      <div class="gtn-disp sel" @click="editing = !editing">
        <el-tag v-if="modelValue" v-bind="tagAttrs(modelValue)" size="small">{{ modelValue }}</el-tag>
        <span v-else class="ph">{{ emptyText }}</span>
      </div>
    </template>
    <div class="gtn-opts">
      <div v-for="o in col.options" :key="o" class="gtn-opt" :class="{ active: modelValue === o }" @click="choose(o)">
        <el-tag v-bind="tagAttrs(o)" size="small">{{ o }}</el-tag>
        <el-icon v-if="modelValue === o" class="gtn-ck"><Check /></el-icon>
      </div>
      <div v-if="modelValue && col.clearable !== false" class="gtn-opt clear" @click="choose(null)">清除</div>
    </div>
  </el-popover>

  <!-- date -->
  <div v-else-if="col.type === 'date'" class="gtn-disp" @click="!editing && start()">
    <el-date-picker v-if="editing" ref="inp" v-model="editVal" type="date" value-format="YYYY-MM-DD"
                    size="small" class="gtn-in" @change="commit" @visible-change="(v) => !v && close()" />
    <template v-else>
      <span v-if="disp !== null">{{ disp }}</span>
      <span v-else class="ph">{{ emptyText }}</span>
    </template>
  </div>

  <!-- long：长文本(如商品标题)。tooltip 包住 div（悬停看全名）；编辑弹窗用 virtual-ref 锚到**同一个 div**
       但不包裹它——两个 popper 互不抢占，既有悬停预览、弹窗又稳稳定位在单元格下方、不飘。 -->
  <template v-else-if="col.long">
    <el-tooltip :content="disp || ''" :disabled="editing || disp === null"
                :show-after="0" placement="top" popper-class="gtn-tip">
      <div ref="cellRef" class="gtn-disp" @click="!editing && start()">
        <span v-if="disp !== null">{{ disp }}</span>
        <span v-else class="ph">{{ emptyText }}</span>
      </div>
    </el-tooltip>
    <!-- 点弹窗外面才关闭并保存(commit 仅值变才 emit)；Esc 取消。固定 4 行不 autosize，防输入时框变高带着弹窗漂移。 -->
    <el-popover :virtual-ref="cellRef" virtual-triggering :visible="editing" :width="380" :offset="4"
                placement="bottom-start" @update:visible="(v) => !v && commit()">
      <el-input ref="inp" v-model="editVal" type="textarea" class="gtn-long-in"
                :rows="4" resize="none" @keydown.esc="close" />
    </el-popover>
  </template>

  <!-- text / decimal / int -->
  <div v-else class="gtn-disp" @click="!editing && start()">
    <el-input-number v-if="editing && col.type === 'int'" ref="inp" v-model="editVal" :controls="false"
                     size="small" class="gtn-in" @blur="commit" @keydown.enter="commit" @keydown.esc="close" />
    <el-input v-else-if="editing" ref="inp" v-model="editVal" size="small" class="gtn-in"
              @blur="commit" @keydown.enter="commit" @keydown.esc="close" />
    <template v-else>
      <span v-if="disp !== null" :class="col.format ? 'derived' : ''">{{ disp }}</span>
      <span v-else class="ph">{{ emptyText }}</span>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Check } from '@element-plus/icons-vue'
import { fmtCNY, fmtJPY } from '@/utils/money'
import { statusStyle, tagStyleAt } from '@/constants'

const props = defineProps({
  modelValue: { default: null },
  col: { type: Object, required: true },
  newRow: { type: Boolean, default: false },   // 幽灵新建行：空值显占位提示引导填写
})
const emit = defineEmits(['change'])

const editing = ref(false)
const editVal = ref(null)
const inp = ref(null)
const cellRef = ref(null)   // long 单元格的 div，供编辑弹窗 virtual-ref 锚定（不包裹、不与 tooltip 抢）
// 统一「柔和底色」标签：标签列按值哈希取色，状态列按语义取色
function tagAttrs(v) {
  if (!props.col.tagColored) return { style: statusStyle(v) }
  // 标签列用后端持久化的颜色序号（稳定不撞色）；缺失则回退按值哈希
  const meta = props.col.tagMeta && props.col.tagMeta[v]
  return { style: tagStyleAt(meta ? meta.color : -1, v) }
}

const disp = computed(() => {
  const v = props.modelValue
  if (v === null || v === undefined || v === '') return null
  if (props.col.format === 'jpy') return fmtJPY(v)
  if (props.col.format === 'cny') return fmtCNY(v)
  return v
})

// 只有幽灵新建行才显占位提示（引导填写）；普通数据行空值一律「—」（select 新建行默认「选择」）
const emptyText = computed(() =>
  props.newRow ? (props.col.placeholder || (props.col.type === 'select' ? '选择' : '—')) : '—',
)

function start() {
  if (props.col.readonly) return
  editVal.value = props.modelValue ?? null
  editing.value = true
  nextTick(() => inp.value?.focus?.())
}
function close() { editing.value = false }
function norm(v) {
  if (v === '' || v === undefined) return null
  if (props.col.type === 'int') return v === null ? null : Number(v)
  return v
}
function commit() {
  if (!editing.value) return          // 防 @blur 与 @keydown.enter 重复提交 → 重复 PATCH
  const raw = editVal.value
  // 数值列基本校验：非法值不提交、保持编辑态（避免脏字符串发后端）
  if ((props.col.type === 'decimal' || props.col.type === 'int')
      && raw !== '' && raw !== null && raw !== undefined && Number.isNaN(Number(raw))) {
    ElMessage.warning('请输入数字')
    return
  }
  editing.value = false
  const v = norm(raw)
  if (String(v ?? '') !== String(props.modelValue ?? '')) emit('change', v)
}
function choose(o) {
  editing.value = false
  if (o !== props.modelValue) emit('change', o)
}
</script>

<style scoped>
.gtn-disp { height: 36px; padding: 0 8px; display: flex; align-items: center; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gtn-disp.sel { cursor: pointer; }
.gtn-disp:hover { background: rgba(24, 144, 255, 0.06); }
.ph { color: #5b6880; }
.derived { color: #8fb8ff; }

.gtn-opts { display: flex; flex-direction: column; gap: 4px; }
.gtn-opt { display: flex; align-items: center; padding: 4px 6px; border-radius: 4px; cursor: pointer; }
.gtn-opt:hover { background: #1b2942; }
.gtn-opt.active { background: rgba(24, 144, 255, 0.15); }
.gtn-ck { margin-left: auto; color: #67c23a; font-size: 14px; }
.gtn-opt.clear { color: #9ba8bf; font-size: 12px; border-top: 1px solid #28354a; }
.gtn-opt.clear:hover { color: #f56c6c; }

/* 长文本弹窗编辑：宽 textarea，失焦自动保存 */
.gtn-long-in { width: 100% !important; }
.gtn-long-in :deep(.el-textarea__inner) { font-size: 13px; }

/* 无边框内嵌输入，像直接在格子里打字（对冲全局 .el-input{width:180px}） */
.gtn-in { width: 100% !important; }
.gtn-in :deep(.el-input__wrapper),
.gtn-in :deep(.el-input-number) { box-shadow: none !important; background: transparent; width: 100% !important; }
.gtn-in :deep(.el-input__inner) { height: 34px; font-size: 13px; color: inherit; text-align: left; }
</style>

<!-- 非 scoped：tooltip 传送到 body，需全局样式；配色对齐暗色主题 -->
<style>
.gtn-tip.el-popper {
  background: #18233a !important;
  border: 1px solid #28354a !important;
  color: #e6edf7 !important;
  max-width: 360px;
}
.gtn-tip.el-popper .el-popper__arrow::before {
  background: #18233a !important;
  border: 1px solid #28354a !important;
}
</style>
