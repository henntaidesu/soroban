// 金额展示格式化。后端是权威：派生的日元由 compute_money 算出，保存后以返回值为准。

export function fmtJPY(n) {
  return n === null || n === undefined ? '—' : '¥' + Number(n).toLocaleString('ja-JP')
}

export function fmtCNY(n) {
  return n === null || n === undefined || n === '' ? '—' : '￥' + Number(n).toFixed(2)
}
