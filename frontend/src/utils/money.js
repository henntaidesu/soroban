// 金额展示格式化。后端是权威：派生的日元由 compute_money 算出，保存后以返回值为准。

// 日元：单位「円」放数字后面（12,345円）；人民币：「￥」放数字前面（￥123.00）
// 非数字（null/空/意外字符串）一律降级为「—」占位，绝不把 NaN 漏给用户看。
export function fmtJPY(n) {
  const x = Number(n)
  return n === null || n === undefined || n === '' || !Number.isFinite(x) ? '—' : x.toLocaleString('ja-JP') + '円'
}

export function fmtCNY(n) {
  const x = Number(n)
  return n === null || n === undefined || n === '' || !Number.isFinite(x) ? '—' : '￥' + x.toFixed(2)
}
