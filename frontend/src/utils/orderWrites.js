// 同一订单的 PATCH 串行化。
// 订单页格子、展开面板、整单编辑面板各自独立发 ordersApi.update，都在调用时读一次
// order.version、拿到响应后才自增。两次编辑若在第一个响应回来前重叠，会带着同一个旧
// version 发出，第二个必 409 → 前端提示「已刷新」并整表重载，用户刚敲的那笔被悄悄丢掉。
//
// 这里按订单 id 把写操作排成一条链：后一个任务在前一个任务（含其 version 回写）完成后才跑，
// 从而恒读到最新 version。任务里必须**完整**包含「读 version → PATCH → 回写 order」，
// 才能保证下一个任务读到的是回写后的新版本。
const chains = new Map()

export function queueOrderWrite(orderId, task) {
  const prev = chains.get(orderId) || Promise.resolve()
  const run = prev.then(task, task)   // 前一个无论成败都接着跑本任务，避免一次失败卡死整条链
  const tail = run.catch(() => {}).finally(() => {
    if (chains.get(orderId) === tail) chains.delete(orderId)   // 链尾跑完即回收，防 Map 泄漏
  })
  chains.set(orderId, tail)
  return run                          // 调用方拿到本任务的真实结果/异常
}
