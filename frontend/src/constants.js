// 状态枚举（必须与后端 models.py 的枚举值一致）
export const TAOBAO_STATUS = ['已付', '已发', '已收', '退款', '已取消']
export const JUNFENG_STATUS = ['打包中', '已发出', '已签收', '已取消']

export function statusTagType(s) {
  return {
    已付: 'info', 已发: 'warning', 已收: 'success', 退款: 'danger', 已取消: 'info',
    打包中: 'warning', 已发出: 'primary', 已签收: 'success',
  }[s] || 'info'
}
