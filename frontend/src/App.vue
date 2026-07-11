<template>
  <router-view />
</template>

<script setup>
</script>

<style>
* { box-sizing: border-box; margin: 0; padding: 0; }

:root.dark { color-scheme: dark; }

/* 暗色主题，对齐 mercari_manage */
html.dark {
  --el-bg-color: #0b1220;
  --el-bg-color-page: #0b1220;
  --el-fill-color-blank: #131c2f;
  --el-fill-color-light: #18233a;
  --el-mask-color: rgba(11, 18, 32, 0.78);
}

html, body, #app {
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
  background: #0b1220;
  color: #e5e7eb;
}

::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-thumb { background: #3a4456; border-radius: 3px; }
::-webkit-scrollbar-track { background: transparent; }

.el-card, .el-dialog, .el-table, .el-input__wrapper,
.el-select__wrapper, .el-textarea__inner { border-color: #2a3446 !important; }

/* 单元格下拉（GotionCell 的 select 弹层）——更紧凑、更像原生菜单 */
.gtn-pop.el-popper {
  padding: 6px !important;
  border: 1px solid #2a3650 !important;
  background: #16203a !important;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45) !important;
}
.gtn-pop.el-popper .el-popper__arrow::before {
  background: #16203a !important;
  border-color: #2a3650 !important;
}

/* 工具栏日期区间筛选：收窄，别霸占整条工具栏（弹性容器里默认会被拉伸） */
.flt-date.el-date-editor.el-date-editor--daterange { width: 244px !important; flex: 0 0 244px !important; }
.flt-date .el-range-separator { padding: 0 2px; flex: none; }

.el-card { background: #131c2f !important; color: #e6edf7; }
.el-card__header { background: #161f33 !important; border-bottom: 1px solid #28354a !important; color: #e6edf7 !important; }
.el-card__body { background: transparent !important; color: #e6edf7; }

.el-loading-mask { background-color: var(--el-mask-color) !important; }

.el-table {
  --el-table-header-bg-color: #18233a;
  --el-table-tr-bg-color: #131c2f;
  --el-table-row-hover-bg-color: #1b2942;
  --el-table-border-color: #28354a;
  color: #d6deea;
}

.el-dialog { --el-dialog-bg-color: #131c2f; }
</style>
