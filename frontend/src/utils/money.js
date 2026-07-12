// 金额展示格式化。后端是权威：派生的日元由 compute_money 算出，保存后以返回值为准。

// 日元：单位「円」放数字后面（12,345円）；人民币：「￥」放数字前面（￥123.00）
export function fmtJPY(n) {
  return n === null || n === undefined ? '—' : Number(n).toLocaleString('ja-JP') + '円'
}

export function fmtCNY(n) {
  return n === null || n === undefined || n === '' ? '—' : '￥' + Number(n).toFixed(2)
}
