import http from './http'

export const authApi = {
  login(username, password) {
    const body = new URLSearchParams()
    body.append('username', username)
    body.append('password', password)
    return http.post('/auth/login', body)
  },
  me: () => http.get('/auth/me'),
  changePassword: (old_password, new_password) =>
    http.post('/auth/change-password', { old_password, new_password }),
}

export const taobaoApi = {
  list: (params) => http.get('/taobao', { params }),
  get: (id) => http.get(`/taobao/${id}`),
  create: (data) => http.post('/taobao', data),
  update: (id, data) => http.patch(`/taobao/${id}`, data),
  remove: (id) => http.delete(`/taobao/${id}`),
}

export const shipmentApi = {
  list: (params) => http.get('/shipment', { params }),
  get: (id) => http.get(`/shipment/${id}`),
  create: (data) => http.post('/shipment', data),
  update: (id, data) => http.patch(`/shipment/${id}`, data),
  remove: (id) => http.delete(`/shipment/${id}`),
  attachTaobao: (shipmentId, tbId) => http.post(`/shipment/${shipmentId}/taobao/${tbId}`),
  detachTaobao: (shipmentId, tbId) => http.delete(`/shipment/${shipmentId}/taobao/${tbId}`),
}

export const miscApi = {
  list: (params) => http.get('/misc', { params }),
  create: (data) => http.post('/misc', data),
  update: (id, data) => http.patch(`/misc/${id}`, data),
  remove: (id) => http.delete(`/misc/${id}`),
}

export const stagingApi = {
  list: (params) => http.get('/staging', { params }),
  create: (data) => http.post('/staging', data),
  update: (id, data) => http.patch(`/staging/${id}`, data),
  remove: (id) => http.delete(`/staging/${id}`),
  ignore: (id) => http.post(`/staging/${id}/ignore`),
  import: (id) => http.post(`/staging/${id}/import`),
}

export const dashboardApi = { get: () => http.get('/dashboard') }
export const fxApi = { get: () => http.get('/fx') }

export const layoutApi = {
  get: (table) => http.get(`/layout/${table}`),
  save: (table, columns) => http.put(`/layout/${table}`, { columns }),
}

// 爬虫插件（soroban 扫 scraper/soroban-scraper-* 作为插件；管理层在插件管理页）
export const pluginsApi = {
  list: () => http.get('/plugins'),
  saveConfig: (id, cfg) => http.put(`/plugins/${id}/config`, cfg),
  login: (id, account) => http.post(`/plugins/${id}/login`, null, { params: { account } }),
  fetch: (id, account) => http.post(`/plugins/${id}/fetch`, null, { params: account ? { account } : {} }),
}

export const tagsApi = {
  list: (field) => http.get(`/tags/${field}`),
  add: (field, value) => http.post(`/tags/${field}`, { value }),
  remove: (field, value) => http.delete(`/tags/${field}/${encodeURIComponent(value)}`),
}
