const deviceApi = '/api/v1';
const deviceTokenKey = 'nbu_iot_access_token';
const deviceState = { organizationId: null, projectId: null, organizationSlug: '', projectSlug: '', mqttConnectionInfo: null, mqttModeByDevice: new Map(), devices: [], selectedId: null, streamController: null, streamGeneration: 0, heartbeatStaleTimer: null, noticeTimer: null, copyFeedbackTimer: null, copyFeedbackButton: null, refreshInFlight: false };
const deviceQuery = (selector, root = document) => root.querySelector(selector);
const escapeDeviceHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
const copyIconMarkup = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></svg>';
const checkIconMarkup = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>';
const deviceTopicNameFromDisplay = (name, fallback) => name.replace(/[^A-Za-z0-9_-]+/g, '_').replace(/^[_-]+|[_-]+$/g, '').slice(0, 80) || fallback.slice(0, 80);
const maxCustomTopicAclsPerDevice = 100;

async function deviceRequest(path, options = {}) {
  const token = sessionStorage.getItem(deviceTokenKey);
  const response = await fetch(deviceApi + path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}), ...(options.headers || {}) },
  });
  if (response.status === 204) return null;
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : data?.detail?.message || 'ทำรายการไม่สำเร็จ');
  return data;
}

function deviceNotice(message, type = 'error') {
  clearTimeout(deviceState.noticeTimer);
  deviceState.noticeTimer = null;
  const notice = deviceQuery('#device-notice');
  notice.textContent = message;
  notice.className = 'device-notice ' + type;
  if (type === 'success') {
    deviceState.noticeTimer = setTimeout(clearDeviceNotice, 2500);
  }
}

function clearDeviceNotice() {
  clearTimeout(deviceState.noticeTimer);
  deviceState.noticeTimer = null;
  const notice = deviceQuery('#device-notice');
  notice.textContent = '';
  notice.className = 'device-notice hidden';
}

function showCredential(result, reason = 'registration') {
  const panel = deviceQuery('#device-credential-panel');
  deviceQuery('#credential-client-id').textContent = result.device.client_id;
  deviceQuery('#credential-username').textContent = result.username;
  deviceQuery('#credential-password').textContent = result.password;
  deviceQuery('#credential-session-note').textContent = reason === 'rotation'
    ? (result.active_session_disconnected ? 'ตัดการเชื่อมต่อเดิมแล้ว' : 'ยังมี session เดิม กรุณา reconnect อุปกรณ์')
    : 'บันทึกรหัสผ่านนี้ไว้ ระบบจะแสดงให้ดูครั้งเดียว';
  panel.classList.remove('hidden');
  panel.dataset.copyText = 'Client ID: ' + result.device.client_id + '\nUsername: ' + result.username + '\nPassword: ' + result.password;
  panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function hideCredential() {
  const panel = deviceQuery('#device-credential-panel');
  ['#credential-client-id', '#credential-username', '#credential-password'].forEach((selector) => { deviceQuery(selector).textContent = ''; });
  panel.dataset.copyText = '';
  panel.classList.add('hidden');
}

function statusLabel(status) {
  return ({ online: 'ออนไลน์', offline: 'ออฟไลน์', unknown: 'ไม่ทราบสถานะ' })[status] || 'ไม่ทราบสถานะ';
}

function updateStatusBadge(badge, status) {
  if (!badge) return;
  badge.classList.remove('online', 'offline', 'unknown');
  const known = ['online', 'offline', 'unknown'];
  const value = known.includes(status) ? status : 'unknown';
  badge.classList.add(value);
  const dot = document.createElement('i');
  badge.replaceChildren(dot, document.createTextNode(statusLabel(value)));
}

function renderDeviceStatusBadges() {
  for (const device of deviceState.devices) {
    const listItem = deviceQuery('.device-list-item[data-device-id="' + device.id + '"]', deviceQuery('#device-list'));
    updateStatusBadge(listItem?.querySelector('.device-status'), device.status);
    if (device.id === deviceState.selectedId) {
      const detail = deviceQuery('#device-detail');
      updateStatusBadge(deviceQuery('[data-device-status]', detail), device.status);
      updateDevicePresenceSummary(device);
    }
  }
}

function heartbeatLabel(status) {
  return ({ active: 'ทำงานปกติ', stale: 'ขาดช่วง', waiting: 'ยังไม่รายงาน' })[status] || 'ไม่ทราบสถานะ';
}

function connectionPortLabel(device) {
  const port = Number(device.last_connection_port);
  if (!Number.isInteger(port) || port < 1 || port > 65535) return 'ยังไม่มีข้อมูลจาก EMQX';
  const encryption = device.last_connection_tls === true ? 'SSL/TLS' : device.last_connection_tls === false ? 'ไม่ใช้ SSL/TLS' : 'ไม่ทราบรูปแบบ';
  return encryption + ' · Port ' + port;
}

function updateMqttModeSelection(device, useTls, portOverride = null) {
  const mqttInfo = deviceState.mqttConnectionInfo;
  if (!mqttInfo || !device) return;
  const configuredPort = Number(useTls ? (mqttInfo.tls_port || 8883) : (mqttInfo.plain_port || 1883));
  const port = Number.isInteger(Number(portOverride)) && Number(portOverride) > 0 ? Number(portOverride) : configuredPort;
  deviceState.mqttModeByDevice.set(device.id, { tls: useTls, port });
  const panel = deviceQuery('#device-detail');
  if (!panel) return;
  panel.querySelectorAll('[data-mqtt-mode]').forEach((option) => {
    const selected = (option.dataset.mqttMode === 'tls') === useTls;
    option.classList.toggle('selected', selected);
    option.setAttribute('aria-pressed', String(selected));
    const optionPort = selected ? port : Number(option.dataset.mqttMode === 'tls' ? (mqttInfo.tls_port || 8883) : (mqttInfo.plain_port || 1883));
    const portLabel = option.querySelector('[data-mqtt-mode-port]');
    if (portLabel) portLabel.textContent = 'Port ' + optionPort;
  });
  const portValue = panel.querySelector('[data-mqtt-port]');
  const copyPort = panel.querySelector('[data-mqtt-port-copy]');
  if (portValue) portValue.textContent = String(port);
  if (copyPort) copyPort.dataset.copyValue = String(port);
  const encryption = panel.querySelector('[data-mqtt-encryption]');
  if (encryption) {
    encryption.classList.toggle('secure', useTls);
    encryption.textContent = useTls ? 'SSL/TLS' : 'ไม่ใช้ SSL/TLS';
  }
}

function syncMqttModeWithOnlineDevice(device) {
  if (device.id !== deviceState.selectedId || device.status !== 'online' || typeof device.last_connection_tls !== 'boolean') return;
  const port = Number(device.last_connection_port);
  if (Number.isInteger(port) && port > 0) updateMqttModeSelection(device, device.last_connection_tls, port);
}

function updateDevicePresenceSummary(device) {
  const panel = deviceQuery('#device-live-summary');
  if (!panel || device.id !== deviceState.selectedId) return;
  const heartbeat = panel.querySelector('[data-heartbeat-status]');
  const heartbeatState = ['active', 'stale', 'waiting'].includes(device.heartbeat_status) ? device.heartbeat_status : 'waiting';
  heartbeat.className = 'heartbeat-chip ' + heartbeatState;
  heartbeat.replaceChildren(document.createElement('i'), document.createTextNode(heartbeatLabel(heartbeatState)));
  panel.querySelector('[data-heartbeat-time]').textContent = device.last_heartbeat_at ? formatDeviceDate(device.last_heartbeat_at) : 'ยังไม่เคยได้รับ heartbeat';
  panel.querySelector('[data-last-seen]').textContent = device.last_seen_at ? formatDeviceDate(device.last_seen_at) : 'ยังไม่มีข้อมูล';
  panel.querySelector('[data-connection-port-label]').textContent = device.status === 'online' ? 'พอร์ตที่ใช้งาน' : 'พอร์ตที่ใช้ล่าสุด';
  panel.querySelector('[data-connection-port]').textContent = connectionPortLabel(device);
  syncMqttModeWithOnlineDevice(device);
}

function scheduleHeartbeatExpiry(device) {
  clearTimeout(deviceState.heartbeatStaleTimer);
  deviceState.heartbeatStaleTimer = null;
  if (!device.last_heartbeat_at) return;
  const deadline = new Date(device.last_heartbeat_at).getTime() + Number(device.heartbeat_timeout_seconds || 90) * 1000;
  const delay = Math.max(0, deadline - Date.now() + 50);
  deviceState.heartbeatStaleTimer = setTimeout(() => {
    const selected = deviceState.devices.find((item) => item.id === deviceState.selectedId);
    if (!selected || !selected.last_heartbeat_at) return;
    if (Date.now() >= new Date(selected.last_heartbeat_at).getTime() + Number(selected.heartbeat_timeout_seconds || 90) * 1000) {
      selected.heartbeat_status = 'stale';
      updateDevicePresenceSummary(selected);
    }
  }, delay);
}

function applyPresenceEvent(update) {
  const device = deviceState.devices.find((item) => item.id === update.id);
  if (!device) return;
  device.status = update.status;
  if (update.heartbeat_status) device.heartbeat_status = update.heartbeat_status;
  if (Object.hasOwn(update, 'last_connection_port')) device.last_connection_port = update.last_connection_port;
  if (Object.hasOwn(update, 'last_connection_tls')) device.last_connection_tls = update.last_connection_tls;
  if (Object.hasOwn(update, 'last_heartbeat_at')) device.last_heartbeat_at = update.last_heartbeat_at;
  if (Object.hasOwn(update, 'last_seen_at')) device.last_seen_at = update.last_seen_at;
  renderDeviceStatusBadges();
  if (device.id === deviceState.selectedId) scheduleHeartbeatExpiry(device);
}

function formatDeviceDate(value) {
  if (!value) return 'ยังไม่เคยเชื่อมต่อ';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('th-TH', { dateStyle: 'medium', timeStyle: 'short' });
}

function filteredDevices() {
  const query = deviceQuery('#device-search').value.trim().toLowerCase();
  return deviceState.devices.filter((device) => !query || device.name.toLowerCase().includes(query) || device.client_id.toLowerCase().includes(query));
}

function renderDeviceList() {
  const list = deviceQuery('#device-list');
  const devices = filteredDevices();
  deviceQuery('#device-count').textContent = deviceState.devices.length + ' อุปกรณ์';
  deviceQuery('#device-empty').classList.toggle('hidden', deviceState.devices.length > 0);
  list.innerHTML = '';
  for (const device of devices) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'device-list-item' + (device.id === deviceState.selectedId ? ' selected' : '');
    button.dataset.deviceId = String(device.id);
    button.innerHTML = '<span class="device-list-icon">◈</span><span class="device-list-copy"><strong>' + escapeDeviceHtml(device.name) + '</strong><small>' + escapeDeviceHtml(device.client_id) + '</small></span><span class="device-status ' + escapeDeviceHtml(device.status) + '"><i></i>' + statusLabel(device.status) + '</span>';
    button.addEventListener('click', () => selectDevice(device.id));
    list.append(button);
  }
  if (deviceState.devices.length && !devices.length) {
    list.innerHTML = '<div class="device-no-results">ไม่พบอุปกรณ์ที่ตรงกับคำค้น</div>';
  }
}

function renderDeviceDetail() {
  const panel = deviceQuery('#device-detail');
  const device = deviceState.devices.find((item) => item.id === deviceState.selectedId);
  if (!device) {
    panel.innerHTML = '<div class="device-detail-placeholder"><div>◈</div><strong>เลือกอุปกรณ์</strong><p>เลือกอุปกรณ์จากรายการเพื่อจัดการรายละเอียด, credential และ topic ACL</p></div>';
    return;
  }
  const projectDevicesPrefix = deviceState.organizationSlug + '/' + deviceState.projectSlug + '/';
  const topicPrefix = projectDevicesPrefix + device.topic_name + '/' + device.client_id + '/';
  const mqttInfo = deviceState.mqttConnectionInfo || { host: location.hostname, port: 1883, plain_port: 1883, tls_port: 8883, tls_enabled: false, host_is_configured: false, mqtt_version_recommended: '3.1.1', keepalive_seconds_recommended: 60 };
  const hasKnownConnectionMode = typeof device.last_connection_tls === 'boolean' && Number(device.last_connection_port) > 0;
  const hasLiveConnectionMode = device.status === 'online' && hasKnownConnectionMode;
  const selectedMode = deviceState.mqttModeByDevice.get(device.id);
  const mqttModeTls = hasLiveConnectionMode ? device.last_connection_tls : (selectedMode?.tls ?? (hasKnownConnectionMode ? device.last_connection_tls : false));
  const mqttModePort = hasLiveConnectionMode ? Number(device.last_connection_port) : Number(selectedMode?.port || (hasKnownConnectionMode ? device.last_connection_port : mqttInfo.plain_port || 1883));
  const plainModePort = !mqttModeTls ? mqttModePort : Number(mqttInfo.plain_port || 1883);
  const tlsModePort = mqttModeTls ? mqttModePort : Number(mqttInfo.tls_port || 8883);
  const customTopicAclCount = device.topics.filter((rule) => !rule.is_system).length;
  const topics = device.topics.map((rule) => {
    const actionLabel = ({ publish: 'ส่งข้อมูล · Publish', subscribe: 'รับข้อมูล · Subscribe', all: 'ส่งและรับ · Publish & Subscribe' })[rule.action] || rule.action;
    return '<tr><td><span class="action-tag ' + escapeDeviceHtml(rule.action) + '">' + escapeDeviceHtml(actionLabel) + '</span></td><td><code>' + escapeDeviceHtml(rule.topic) + '</code><small>QoS ' + escapeDeviceHtml(rule.qos.join(', ')) + ' · Retain ' + escapeDeviceHtml(rule.retain) + (rule.is_system ? ' · กฎพื้นฐาน' : '') + '</small></td><td><div class="topic-row-actions"><button type="button" class="secondary copy-icon-button" data-copy-topic="' + escapeDeviceHtml(rule.topic) + '" aria-label="คัดลอก Topic" title="คัดลอก Topic">' + copyIconMarkup + '</button>' + (rule.is_system ? '' : '<button type="button" class="icon-danger" data-remove-topic="' + rule.id + '" aria-label="ลบ ACL" title="ลบ ACL">×</button>') + '</div></td></tr>';
  }).join('');
  panel.innerHTML = '<div class="device-detail-head"><div><span class="eyebrow">DEVICE DETAILS</span><h3>' + escapeDeviceHtml(device.name) + '</h3></div></div>' +
    '<section id="device-live-summary" class="device-live-summary"><div class="presence-summary-item"><small>MQTT Session</small><span class="device-status ' + escapeDeviceHtml(device.status) + '" data-device-status><i></i>' + statusLabel(device.status) + '</span><span class="presence-detail"><span data-connection-port-label>' + (device.status === 'online' ? 'พอร์ตที่ใช้งาน' : 'พอร์ตที่ใช้ล่าสุด') + '</span><b data-connection-port>' + connectionPortLabel(device) + '</b></span></div><div class="presence-summary-item"><small>Heartbeat</small><span class="heartbeat-chip ' + escapeDeviceHtml(device.heartbeat_status || 'waiting') + '" data-heartbeat-status><i></i>' + heartbeatLabel(device.heartbeat_status) + '</span><span class="presence-detail">ล่าสุด <b data-heartbeat-time>' + (device.last_heartbeat_at ? formatDeviceDate(device.last_heartbeat_at) : 'ยังไม่เคยได้รับ heartbeat') + '</b></span></div><div class="presence-summary-item"><small>พบอุปกรณ์ล่าสุด</small><strong data-last-seen>' + (device.last_seen_at ? formatDeviceDate(device.last_seen_at) : 'ยังไม่มีข้อมูล') + '</strong></div></section>' +
    '<form id="device-name-form" class="device-name-form"><label>ชื่ออุปกรณ์<input name="name" value="' + escapeDeviceHtml(device.name) + '" minlength="2" maxlength="160" required></label><button class="secondary" type="submit">บันทึกชื่อ</button></form>' +
    '<section class="mqtt-connection-card"><header class="mqtt-connection-header"><span class="mqtt-connection-icon">⌁</span><div><h4>ข้อมูลเชื่อมต่อ MQTT</h4><p>ค่าที่ต้องใช้ตั้งค่า MQTT client ในอุปกรณ์</p></div></header>' +
    '<div class="mqtt-connection-mode" role="group" aria-label="รูปแบบการเชื่อมต่อ MQTT"><button type="button" data-mqtt-mode="plain" aria-pressed="' + (!mqttModeTls) + '" class="' + (!mqttModeTls ? 'selected' : '') + '"><strong>ไม่ใช้ SSL/TLS</strong><small data-mqtt-mode-port>Port ' + escapeDeviceHtml(plainModePort) + '</small></button><button type="button" data-mqtt-mode="tls" aria-pressed="' + Boolean(mqttModeTls) + '" class="' + (mqttModeTls ? 'selected' : '') + '"><strong>ใช้ SSL/TLS</strong><small data-mqtt-mode-port>Port ' + escapeDeviceHtml(tlsModePort) + '</small></button></div>' +
    '<p class="mqtt-mode-note">เลือกค่าให้ตรงกับ listener ที่เปิดใช้งานบน EMQX; SSL/TLS ต้องมี listener และ certificate พร้อมใช้งาน</p>' +
    '<div class="mqtt-connection-grid"><div class="mqtt-connection-item"><small>Broker Host</small><div><code>' + escapeDeviceHtml(mqttInfo.host || 'ยังไม่ได้กำหนด') + '</code><button type="button" class="secondary copy-icon-button" data-copy-value="' + escapeDeviceHtml(mqttInfo.host || '') + '" aria-label="คัดลอก Broker Host" title="คัดลอก Broker Host">' + copyIconMarkup + '</button></div></div>' +
    '<div class="mqtt-connection-item"><small>Port</small><div><code data-mqtt-port>' + escapeDeviceHtml(mqttModePort) + '</code><button type="button" class="secondary copy-icon-button" data-mqtt-port-copy data-copy-value="' + escapeDeviceHtml(mqttModePort) + '" aria-label="คัดลอก Port" title="คัดลอก Port">' + copyIconMarkup + '</button></div></div>' +
    '<div class="mqtt-connection-item"><small>การเข้ารหัส</small><div><span class="mqtt-value-chip ' + (mqttModeTls ? 'secure' : '') + '" data-mqtt-encryption>' + (mqttModeTls ? 'SSL/TLS' : 'ไม่ใช้ SSL/TLS') + '</span></div></div>' +
    '<div class="mqtt-connection-item"><small>MQTT Version แนะนำ</small><div><span class="mqtt-value-chip">' + escapeDeviceHtml(mqttInfo.mqtt_version_recommended || '3.1.1') + '</span></div></div>' +
    '<div class="mqtt-connection-item"><small>Client ID</small><div><code>' + escapeDeviceHtml(device.client_id) + '</code><button type="button" class="secondary copy-icon-button" data-copy-client aria-label="คัดลอก Client ID" title="คัดลอก Client ID">' + copyIconMarkup + '</button></div></div>' +
    '<div class="mqtt-connection-item"><small>Username</small><div><code>' + escapeDeviceHtml(device.client_id) + '</code><button type="button" class="secondary copy-icon-button" data-copy-value="' + escapeDeviceHtml(device.client_id) + '" aria-label="คัดลอก Username" title="คัดลอก Username">' + copyIconMarkup + '</button></div></div></div>' +
    (!mqttInfo.host_is_configured ? '<p class="mqtt-config-note">Broker Host แสดงตามที่อยู่หน้าเว็บ หากอุปกรณ์อยู่อีกเครื่อง ให้ตั้งค่า <code>EMQX_MQTT_PUBLIC_HOST</code> เป็น IP/โดเมนที่อุปกรณ์เข้าถึงได้</p>' : '') +
    '<div class="mqtt-password-note"><span class="mqtt-password-icon">i</span><p><strong>Password</strong> แสดงครั้งเดียวตอนลงทะเบียนหรือเปลี่ยนรหัสผ่าน หากไม่มีรหัสผ่าน ให้ใช้ปุ่ม “เปลี่ยนรหัสผ่าน” ด้านล่างแล้วบันทึกค่าใหม่ไว้</p></div>' +
    '<div class="mqtt-recommended-settings"><span>ค่าแนะนำ</span><b>Keep Alive ' + escapeDeviceHtml(mqttInfo.keepalive_seconds_recommended || 60) + ' วินาที</b><i>Session: Clean Session; ใช้ Persistent Session + QoS 1 หากต้องรับคำสั่งระหว่างออฟไลน์</i><i>ใช้ Client ID เดิมของอุปกรณ์นี้ทุกครั้งที่ reconnect</i></div></section>' +
    '<section class="topic-manager"><header class="topic-manager-heading"><span class="topic-manager-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 3 20 6v5c0 5-3.4 8.2-8 10-4.6-1.8-8-5-8-10V6l8-3Z"/><path d="m8.5 12 2.2 2.2 4.8-4.8"/></svg></span><div><h4>Topic ACL</h4><p>กฎพื้นฐานไม่นับโควตา · เพิ่มเอง ${customTopicAclCount}/${maxCustomTopicAclsPerDevice} ต่ออุปกรณ์ (มีโควตารวมตามแพ็กเกจ)</p></div></header><div class="topic-prefix"><div class="topic-prefix-copy"><small>Topic prefix ของอุปกรณ์นี้</small><code>' + escapeDeviceHtml(topicPrefix) + '</code></div><button type="button" class="secondary copy-icon-button" data-copy-value="' + escapeDeviceHtml(topicPrefix) + '" aria-label="คัดลอก Topic prefix" title="คัดลอก Topic prefix">' + copyIconMarkup + '</button></div>' +
    '<div class="topic-table-wrap"><table class="topic-table"><thead><tr><th>สิทธิ์</th><th>Topic filter</th><th></th></tr></thead><tbody>' + (topics || '<tr><td colspan="3" class="device-no-results">ยังไม่มีกฎ ACL — อุปกรณ์ถูกปฏิเสธ topic ทั้งหมด</td></tr>') + '</tbody></table></div>' +
    '<form id="device-topic-form" class="topic-create-form"><label>สิทธิ์<select name="action"><option value="publish">ส่งข้อมูล · Publish</option><option value="subscribe">รับข้อมูล · Subscribe</option><option value="all">ส่งและรับข้อมูล · Publish &amp; Subscribe</option></select></label><label class="topic-input-label">Topic filter<input name="topic" required maxlength="512" placeholder="' + escapeDeviceHtml(projectDevicesPrefix + '{device_topic_name}/{client_id}/custom/#') + '"></label><button class="primary" type="submit" ' + (customTopicAclCount >= maxCustomTopicAclsPerDevice ? 'disabled' : '') + '>เพิ่ม ACL</button></form></section>' +
    '<section class="device-manage-card"><header><div><h4>จัดการอุปกรณ์</h4><p>เปลี่ยน credential หรือเอาอุปกรณ์ออกจากโปรเจกต์</p></div></header><div class="device-actions"><button type="button" class="secondary" data-rotate-credentials>↻ เปลี่ยนรหัสผ่าน</button><button type="button" class="danger-button" data-delete-device>ลบอุปกรณ์</button></div></section>';
  panel.querySelector('#device-name-form').addEventListener('submit', updateDeviceName);
  panel.querySelector('#device-topic-form').addEventListener('submit', addDeviceTopic);
  panel.querySelectorAll('[data-mqtt-mode]').forEach((button) => button.addEventListener('click', () => {
    updateMqttModeSelection(device, button.dataset.mqttMode === 'tls');
  }));
  scheduleHeartbeatExpiry(device);
}

function selectDevice(deviceId) {
  clearDeviceNotice();
  resetCopyFeedback();
  deviceState.selectedId = deviceId;
  renderDeviceList();
  renderDeviceDetail();
}

async function refreshProjectDevices({ keepSelection = true } = {}) {
  if (deviceState.refreshInFlight || !deviceQuery('#device-dialog').open) return;
  deviceState.refreshInFlight = true;
  clearDeviceNotice();
  const previousId = keepSelection ? deviceState.selectedId : null;
  try {
    deviceState.devices = await deviceRequest('/organizations/' + deviceState.organizationId + '/projects/' + deviceState.projectId + '/devices');
    deviceState.selectedId = deviceState.devices.some((device) => device.id === previousId) ? previousId : (deviceState.devices[0]?.id ?? null);
    renderDeviceList();
    renderDeviceDetail();
    renderDeviceStatusBadges();
  } catch (error) {
    deviceNotice(error.message);
  } finally {
    deviceState.refreshInFlight = false;
  }
}

function processDeviceEvent(eventName, data) {
  if (eventName === 'snapshot' && Array.isArray(data)) {
    data.forEach(applyPresenceEvent);
  } else if (eventName === 'device_status' && data && typeof data === 'object') {
    applyPresenceEvent(data);
  }
}

function stopDeviceStatusStream() {
  deviceState.streamGeneration += 1;
  if (deviceState.streamController) deviceState.streamController.abort();
  deviceState.streamController = null;
}

function startDeviceStatusStream() {
  stopDeviceStatusStream();
  const generation = deviceState.streamGeneration;
  void runDeviceStatusStream(generation);
}

async function runDeviceStatusStream(generation) {
  let retryMs = 1000;
  const liveLabel = deviceQuery('#device-live-indicator');
  while (deviceQuery('#device-dialog').open && generation === deviceState.streamGeneration) {
    const controller = new AbortController();
    deviceState.streamController = controller;
    try {
      const token = sessionStorage.getItem(deviceTokenKey);
      const response = await fetch(deviceApi + '/organizations/' + deviceState.organizationId + '/projects/' + deviceState.projectId + '/devices/events', {
        headers: token ? { Authorization: 'Bearer ' + token } : {},
        signal: controller.signal,
      });
      if (!response.ok || !response.body) throw new Error('SSE connection failed');
      if (liveLabel) liveLabel.textContent = 'รับสถานะและ heartbeat จาก EMQX';
      retryMs = 1000;
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (deviceQuery('#device-dialog').open && generation === deviceState.streamGeneration) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let boundary;
        while ((boundary = buffer.search(/\r?\n\r?\n/)) !== -1) {
          const block = buffer.slice(0, boundary);
          const separator = buffer.slice(boundary).match(/^\r?\n\r?\n/)[0];
          buffer = buffer.slice(boundary + separator.length);
          let eventName = 'message';
          const dataLines = [];
          for (const line of block.split(/\r?\n/)) {
            if (line.startsWith('event:')) eventName = line.slice(6).trim();
            else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
          }
          if (dataLines.length) {
            try { processDeviceEvent(eventName, JSON.parse(dataLines.join('\n'))); } catch { /* Ignore malformed stream frames. */ }
          }
        }
      }
      if (controller.signal.aborted || generation !== deviceState.streamGeneration) return;
      throw new Error('SSE stream ended');
    } catch {
      if (controller.signal.aborted || generation !== deviceState.streamGeneration) return;
      if (liveLabel) liveLabel.textContent = 'กำลังเชื่อมต่อ event อีกครั้ง…';
      await new Promise((resolve) => setTimeout(resolve, retryMs));
      retryMs = Math.min(retryMs * 2, 15000);
    }
  }
}

async function openProjectDevices(organizationId, projectId) {
  deviceState.organizationId = organizationId;
  deviceState.projectId = projectId;
  deviceState.selectedId = null;
  deviceState.devices = [];
  hideCredential();
  deviceQuery('#device-create-form').classList.add('hidden');
  deviceQuery('#device-project-title').textContent = 'จัดการอุปกรณ์';
  deviceQuery('#device-project-subtitle').textContent = 'กำลังโหลดโปรเจกต์…';
  deviceQuery('#device-project-description').textContent = '';
  deviceQuery('#device-project-description').classList.add('hidden');
  deviceQuery('#device-dialog').showModal();
  try {
    const [organizations, projects, mqttConnectionInfo] = await Promise.all([
      deviceRequest('/organizations'),
      deviceRequest('/organizations/' + organizationId + '/projects'),
      deviceRequest('/mqtt/connection-info'),
    ]);
    const organization = organizations.find((item) => item.id === organizationId);
    const project = projects.find((item) => item.id === projectId);
    if (!organization || !project) throw new Error('ไม่พบองค์กรหรือโปรเจกต์นี้');
    deviceState.organizationSlug = organization.slug;
    deviceState.projectSlug = project.slug;
    deviceState.mqttConnectionInfo = mqttConnectionInfo;
    deviceQuery('#device-project-title').textContent = project.name;
    deviceQuery('#device-project-subtitle').textContent = organization.name + '  /  ' + project.slug;
    const projectDescription = deviceQuery('#device-project-description');
    projectDescription.textContent = project.description || '';
    projectDescription.classList.toggle('hidden', !project.description?.trim());
    await refreshProjectDevices({ keepSelection: false });
    startDeviceStatusStream();
  } catch (error) {
    deviceNotice(error.message);
  }
}

async function createDevice(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('[type="submit"]');
  submit.disabled = true;
  clearDeviceNotice();
  const fields = new FormData(form);
  try {
    const result = await deviceRequest('/organizations/' + deviceState.organizationId + '/projects/' + deviceState.projectId + '/devices', {
      method: 'POST', body: JSON.stringify({ name: fields.get('name'), client_id: fields.get('client_id') || null }),
    });
    form.reset();
    form.classList.add('hidden');
    showCredential(result);
    await refreshProjectDevices({ keepSelection: false });
    deviceState.selectedId = result.device.id;
    renderDeviceList();
    renderDeviceDetail();
    if (typeof loadBillingUsage === 'function') await loadBillingUsage();
  } catch (error) {
    deviceNotice(error.message);
  } finally {
    submit.disabled = false;
  }
}

async function updateDeviceName(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const device = deviceState.devices.find((item) => item.id === deviceState.selectedId);
  if (!device) return;
  const newName = String(new FormData(form).get('name') || '').trim();
  const newTopicName = deviceTopicNameFromDisplay(newName, device.client_id);
  const topicNameChanged = newTopicName !== device.topic_name;
  if (topicNameChanged && !(await confirmApp('การเปลี่ยนชื่อนี้จะเปลี่ยน Topic Name และอัปเดต ACL ของอุปกรณ์ที่เกี่ยวข้อง โปรดแก้ Topic ใน firmware ของอุปกรณ์ที่ส่ง/รับด้วย\n\nTopic Name เดิม: ' + device.topic_name + '\nTopic Name ใหม่: ' + newTopicName,{title:'เปลี่ยน Topic Name',confirmLabel:'เปลี่ยนชื่อและอัปเดต ACL'}))) return;
  const submit = form.querySelector('[type="submit"]');
  submit.disabled = true;
  try {
    const updated = await deviceRequest('/devices/' + device.id, { method: 'PATCH', body: JSON.stringify({ name: newName }) });
    deviceNotice(topicNameChanged ? 'เปลี่ยนชื่อและ Topic Name แล้ว · อัปเดต firmware เป็น ' + updated.topic_name : 'บันทึกชื่ออุปกรณ์แล้ว', 'success');
    await refreshProjectDevices();
  } catch (error) { deviceNotice(error.message); }
  finally { submit.disabled = false; }
}

async function addDeviceTopic(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const device = deviceState.devices.find((item) => item.id === deviceState.selectedId);
  if (!device) return;
  const fields = new FormData(form);
  const submit = form.querySelector('[type="submit"]');
  submit.disabled = true;
  try {
    await deviceRequest('/devices/' + device.id + '/topics', { method: 'POST', body: JSON.stringify({ topic: fields.get('topic'), action: fields.get('action') }) });
    deviceNotice('เพิ่ม topic ACL แล้ว', 'success');
    await refreshProjectDevices();
    if (typeof loadBillingUsage === 'function') await loadBillingUsage();
  } catch (error) { deviceNotice(error.message); }
  finally { submit.disabled = false; }
}

async function rotateDeviceCredentials() {
  const device = deviceState.devices.find((item) => item.id === deviceState.selectedId);
  if (!device || !await confirmApp('ออก credential ใหม่ให้อุปกรณ์นี้หรือไม่? รหัสผ่านเดิมจะใช้ไม่ได้เมื่อเชื่อมต่อครั้งถัดไป',{title:'ออก credential ใหม่',confirmLabel:'ออก credential'})) return;
  try {
    const result = await deviceRequest('/devices/' + device.id + '/credentials/rotate', { method: 'POST' });
    showCredential(result, 'rotation');
    await refreshProjectDevices();
  } catch (error) { deviceNotice(error.message); }
}

async function removeDevice() {
  const device = deviceState.devices.find((item) => item.id === deviceState.selectedId);
  if (!device || !await confirmApp('ลบ ' + device.name + ' พร้อม credential และ ACL จาก EMQX หรือไม่?',{title:'ลบอุปกรณ์',confirmLabel:'ลบอุปกรณ์',danger:true})) return;
  try {
    await deviceRequest('/devices/' + device.id, { method: 'DELETE' });
    hideCredential();
    deviceState.selectedId = null;
    deviceNotice('ลบอุปกรณ์แล้ว', 'success');
    await refreshProjectDevices({ keepSelection: false });
    if (typeof loadBillingUsage === 'function') await loadBillingUsage();
  } catch (error) { deviceNotice(error.message); }
}

async function removeDeviceTopic(topicId) {
  const device = deviceState.devices.find((item) => item.id === deviceState.selectedId);
  const topic = device?.topics.find((item) => item.id === topicId);
  if (!device || !topic || !await confirmApp('ลบสิทธิ์ ' + topic.action + ' ที่ topic นี้หรือไม่?',{title:'ลบ Topic ACL',confirmLabel:'ลบสิทธิ์',danger:true})) return;
  try {
    await deviceRequest('/devices/' + device.id + '/topics/' + topic.id, { method: 'DELETE' });
    deviceNotice('ลบ topic ACL แล้ว', 'success');
    await refreshProjectDevices();
    if (typeof loadBillingUsage === 'function') await loadBillingUsage();
  } catch (error) { deviceNotice(error.message); }
}

function resetCopyFeedback() {
  clearTimeout(deviceState.copyFeedbackTimer);
  deviceState.copyFeedbackTimer = null;
  const button = deviceState.copyFeedbackButton;
  if (button?.isConnected) {
    button.innerHTML = button.dataset.copyIdleHtml || copyIconMarkup;
    button.classList.remove('copy-confirmed');
    if (button.dataset.copyIdleAria) button.setAttribute('aria-label', button.dataset.copyIdleAria); else button.removeAttribute('aria-label');
    if (button.dataset.copyIdleTitle) button.title = button.dataset.copyIdleTitle; else button.removeAttribute('title');
  }
  deviceState.copyFeedbackButton = null;
}

function showCopyFeedback(button) {
  resetCopyFeedback();
  if (!button) return;
  button.dataset.copyIdleHtml = button.innerHTML;
  button.dataset.copyIdleAria = button.getAttribute('aria-label') || '';
  button.dataset.copyIdleTitle = button.title || '';
  button.classList.add('copy-confirmed');
  button.classList.add('copy-feedback-target');
  button.innerHTML = checkIconMarkup;
  button.setAttribute('aria-label', 'คัดลอกแล้ว');
  button.title = 'คัดลอกแล้ว';
  deviceState.copyFeedbackButton = button;
  deviceState.copyFeedbackTimer = setTimeout(resetCopyFeedback, 1600);
}

async function copyText(value, button) {
  try {
    await navigator.clipboard.writeText(value);
    clearDeviceNotice();
    showCopyFeedback(button);
  } catch {
    deviceNotice('คัดลอกไม่ได้จากเบราว์เซอร์นี้ กรุณาเลือกและคัดลอกข้อความเอง');
  }
}

function attachDeviceButtons(root) {
  root.querySelectorAll('.project-row[data-project-id]:not([data-device-button])').forEach((row) => {
    row.dataset.deviceButton = 'true';
    const button = document.createElement('button');
    button.className = 'secondary device-manager';
    button.type = 'button';
    button.textContent = 'อุปกรณ์';
    button.addEventListener('click', () => openProjectDevices(Number(row.dataset.orgId), Number(row.dataset.projectId)));
    row.append(button);
  });
}

deviceQuery('#device-create-form').addEventListener('submit', createDevice);
deviceQuery('#device-add-toggle').addEventListener('click', () => {
  const form = deviceQuery('#device-create-form');
  form.classList.toggle('hidden');
  if (!form.classList.contains('hidden')) form.querySelector('[name="name"]').focus();
});
deviceQuery('#device-empty-add').addEventListener('click', () => deviceQuery('#device-add-toggle').click());
deviceQuery('#device-create-cancel').addEventListener('click', () => deviceQuery('#device-create-form').classList.add('hidden'));
deviceQuery('#device-refresh').addEventListener('click', () => refreshProjectDevices());
deviceQuery('#device-close').addEventListener('click', () => deviceQuery('#device-dialog').close());
deviceQuery('#device-search').addEventListener('input', renderDeviceList);
deviceQuery('#credential-dismiss').addEventListener('click', hideCredential);
deviceQuery('#credential-copy').addEventListener('click', (event) => copyText(deviceQuery('#device-credential-panel').dataset.copyText || '', event.currentTarget));
deviceQuery('#device-dialog').addEventListener('close', () => {
  stopDeviceStatusStream();
  clearTimeout(deviceState.heartbeatStaleTimer);
  deviceState.heartbeatStaleTimer = null;
  hideCredential();
  if (typeof loadBillingUsage === 'function') void loadBillingUsage();
});
deviceQuery('#device-detail').addEventListener('click', (event) => {
  if (event.target.closest('[data-rotate-credentials]')) rotateDeviceCredentials();
  if (event.target.closest('[data-delete-device]')) removeDevice();
  if (event.target.closest('[data-copy-client]')) {
    const device = deviceState.devices.find((item) => item.id === deviceState.selectedId);
    if (device) copyText(device.client_id, event.target.closest('[data-copy-client]'));
  }
  const copyTopicButton = event.target.closest('[data-copy-topic]');
  if (copyTopicButton) copyText(copyTopicButton.dataset.copyTopic, copyTopicButton);
  const copyValueButton = event.target.closest('[data-copy-value]');
  if (copyValueButton) copyText(copyValueButton.dataset.copyValue, copyValueButton);
  const removeButton = event.target.closest('[data-remove-topic]');
  if (removeButton) removeDeviceTopic(Number(removeButton.dataset.removeTopic));
});

const deviceOrganizationList = document.querySelector('#org-list');
if (deviceOrganizationList) {
  const deviceButtonObserver = new MutationObserver(() => attachDeviceButtons(deviceOrganizationList));
  deviceButtonObserver.observe(deviceOrganizationList, { childList: true, subtree: true });
  attachDeviceButtons(deviceOrganizationList);
}
