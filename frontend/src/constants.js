// 状态枚举（必须与后端 models.py 的枚举值一致）
// 淘宝交易状态（对齐淘宝：待付款→待发货→待收货→交易成功 / 退款 / 交易关闭）
export const TAOBAO_STATUS = ['待付款', '待发货', '待收货', '交易成功', '退款', '交易关闭']
export const SHIPMENT_STATUS = ['打包中', '已发出', '已签收', '已取消']
export const STAGING_STATUS = ['待处理', '已导入', '已忽略']   // 暂存导入工作流状态

export function statusTagType(s) {
  return {
    待付款: 'info', 待发货: 'warning', 待收货: 'primary', 交易成功: 'success', 退款: 'danger', 交易关闭: 'info',
    打包中: 'warning', 已发出: 'primary', 已签收: 'success', 已取消: 'info',
  }[s] || 'info'
}

export function stagingTag(s) {
  return { 待处理: 'warning', 已导入: 'success', 已忽略: 'info' }[s] || 'info'
}

// 标签调色盘（管理型标签列：淘宝号/收货人等）——每个值哈希到固定一色，暗色主题友好的柔和底色
export const TAG_PALETTE = [
  { bg: 'rgba(59,130,246,.18)', border: 'rgba(59,130,246,.45)', text: '#8ab4ff' },   // 蓝
  { bg: 'rgba(16,185,129,.18)', border: 'rgba(16,185,129,.45)', text: '#4ade9f' },   // 绿
  { bg: 'rgba(245,158,11,.18)', border: 'rgba(245,158,11,.45)', text: '#f0b64d' },   // 琥珀
  { bg: 'rgba(239,68,68,.18)',  border: 'rgba(239,68,68,.45)',  text: '#f78b8b' },   // 红
  { bg: 'rgba(139,92,246,.18)', border: 'rgba(139,92,246,.45)', text: '#b79cff' },   // 紫
  { bg: 'rgba(236,72,153,.18)', border: 'rgba(236,72,153,.45)', text: '#f38bc4' },   // 粉
  { bg: 'rgba(20,184,166,.18)', border: 'rgba(20,184,166,.45)', text: '#4fd6c4' },   // 青
  { bg: 'rgba(249,115,22,.18)', border: 'rgba(249,115,22,.45)', text: '#fba95f' },   // 橙
  { bg: 'rgba(99,102,241,.18)', border: 'rgba(99,102,241,.45)', text: '#9fa2ff' },   // 靛
  { bg: 'rgba(132,204,22,.18)', border: 'rgba(132,204,22,.45)', text: '#a7e05a' },   // 黄绿
]

export function tagColor(value) {
  const s = String(value ?? '')
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return TAG_PALETTE[h % TAG_PALETTE.length]
}
function _css(c) {
  return `background:${c.bg};border-color:${c.border};color:${c.text}`
}
export function tagStyle(value) {   // 管理型标签（账号/收货人）：按值哈希取色
  return _css(tagColor(value))
}

// 状态标签统一成同款「柔和底色」——只是按语义 type 取色（不用哈希），保留含义、观感一致
const GREY = { bg: 'rgba(148,163,184,.16)', border: 'rgba(148,163,184,.4)', text: '#aab6c9' }
const TYPE_TINT = {
  primary: TAG_PALETTE[0], success: TAG_PALETTE[1], warning: TAG_PALETTE[2], danger: TAG_PALETTE[3], info: GREY,
}
export function typeStyle(type) {
  return _css(TYPE_TINT[type] || GREY)
}
export function statusStyle(s) {
  return typeStyle(statusTagType(s))
}
export function stagingStyle(s) {
  return typeStyle(stagingTag(s))
}
