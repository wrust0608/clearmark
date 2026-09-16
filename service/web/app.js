const $ = (selector, root = document) => root.querySelector(selector);
const state = { files: [], apiKey: sessionStorage.getItem('clearmark-api-key') || '' };
const els = {
  drop: $('#dropZone'), input: $('#fileInput'), browse: $('#browseButton'), list: $('#fileList'),
  bar: $('#actionBar'), count: $('#selectionCount'), size: $('#selectionSize'), cleanAll: $('#cleanAllButton'),
  clear: $('#clearButton'), server: $('#serverState'), toast: $('#toast'), dialog: $('#settingsDialog'), key: $('#apiKey')
};

function formatBytes(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function authHeaders() {
  const headers = { 'Content-Type': 'application/json' };
  if (state.apiKey) headers.Authorization = `Bearer ${state.apiKey}`;
  return headers;
}

async function api(path, file) {
  const body = { name: file.name, file: await toBase64(file) };
  if (path === '/clean') {
    const isDocx = file.name.toLowerCase().endsWith('.docx');
    body.options = isDocx
      ? { also_layer_a_text: true, normalize_spaces: false }
      : { layer_a_only: true };
  }
  const response = await fetch(path, { method: 'POST', headers: authHeaders(), body: JSON.stringify(body) });
  let data;
  try { data = await response.json(); } catch { throw new Error('Máy chủ trả về dữ liệu không hợp lệ.'); }
  if (!response.ok || !data.ok) {
    if (response.status === 401) throw new Error('Cần nhập đúng khóa truy cập.');
    if (response.status === 413) throw new Error('Tệp vượt quá giới hạn của máy chủ.');
    throw new Error(data.error || 'Không thể xử lý tệp.');
  }
  return data;
}

function toBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.onerror = () => reject(new Error('Không thể đọc tệp.'));
    reader.readAsDataURL(file);
  });
}

function fromBase64(value, type) {
  const binary = atob(value); const parts = [];
  for (let offset = 0; offset < binary.length; offset += 8192) {
    const slice = binary.slice(offset, offset + 8192);
    parts.push(Uint8Array.from(slice, char => char.charCodeAt(0)));
  }
  return new Blob(parts, { type: type || 'application/octet-stream' });
}

function showToast(message) {
  els.toast.textContent = message; els.toast.classList.add('show');
  clearTimeout(showToast.timer); showToast.timer = setTimeout(() => els.toast.classList.remove('show'), 2600);
}

function ext(name) { return (name.split('.').pop() || 'FILE').slice(0, 5).toUpperCase(); }
function cleanedName(name) { const dot = name.lastIndexOf('.'); return dot > 0 ? `${name.slice(0, dot)}.clean${name.slice(dot)}` : `${name}.clean`; }

function resultFile(item) {
  if (!item.result) return item.file;
  return new File([item.result.blob], item.result.name, {
    type: item.file.type || 'application/octet-stream',
    lastModified: Date.now()
  });
}

function addFiles(fileList) {
  for (const file of fileList) {
    const id = `${file.name}-${file.size}-${file.lastModified}`;
    if (!state.files.some(item => item.id === id)) state.files.push({ id, file, result: null, status: 'ready' });
  }
  render();
}

function render() {
  els.list.replaceChildren();
  els.bar.hidden = state.files.length === 0;
  els.count.textContent = `${state.files.length} tệp đã chọn`;
  els.size.textContent = formatBytes(state.files.reduce((sum, item) => sum + item.file.size, 0));
  state.files.forEach(item => {
    const node = $('#fileCardTemplate').content.firstElementChild.cloneNode(true);
    node.dataset.id = item.id; node.classList.toggle('busy', item.status === 'busy'); node.classList.toggle('error', item.status === 'error');
    $('.file-name', node).textContent = item.file.name; $('.file-size', node).textContent = formatBytes(item.file.size); $('.file-ext', node).textContent = ext(item.file.name);
    const kind = $('.file-kind', node); const detail = $('.file-detail', node);
    const labels = { ready: 'Sẵn sàng', busy: 'Đang xử lý…', inspected: 'Đã kiểm tra', cleaned: 'Đã làm sạch', error: 'Có lỗi' };
    kind.textContent = labels[item.status] || labels.ready; detail.textContent = item.detail || '';
    if (item.file.type.startsWith('image/')) {
      const url = URL.createObjectURL(item.result?.blob || item.file); $('.file-thumb', node).style.backgroundImage = `url("${url}")`; $('.file-ext', node).textContent = '';
      node.addEventListener('DOMNodeRemoved', () => URL.revokeObjectURL(url), { once: true });
    }
    $('.inspect-file', node).disabled = item.status === 'busy'; $('.clean-file', node).disabled = item.status === 'busy';
    $('.download-file', node).hidden = !item.result;
    $('.remove-file', node).onclick = () => { state.files = state.files.filter(x => x.id !== item.id); render(); };
    $('.inspect-file', node).onclick = () => inspectItem(item);
    $('.clean-file', node).onclick = () => cleanItem(item);
    $('.download-file', node).onclick = () => downloadItem(item);
    els.list.appendChild(node);
  });
}

function inspectionSummary(data) {
  const suspicious = data.suspicious || {};
  if (suspicious.verdict) {
    const classes = Object.values(suspicious.classes || {}).filter(value => value?.present).length;
    return `Phát hiện dấu vết cần làm sạch${classes ? ` trong ${classes} nhóm` : ''}.`;
  }
  return 'Không phát hiện dấu vết rõ ràng. Bạn vẫn có thể làm sạch metadata.';
}

async function inspectItem(item) {
  item.status = 'busy'; item.detail = 'Đang phân tích cấu trúc và metadata…'; render();
  try {
    const inspectingCleanedResult = Boolean(item.result);
    const data = await api('/inspect', resultFile(item));
    item.status = inspectingCleanedResult ? 'cleaned' : 'inspected';
    item.detail = inspectingCleanedResult && !data.suspicious?.verdict
      ? 'Đã xác minh · bản tải xuống không còn dấu vết được phát hiện.'
      : inspectionSummary(data);
  }
  catch (error) { item.status = 'error'; item.detail = error.message; }
  render();
}

async function cleanItem(item, quiet = false) {
  const isDocx = item.file.name.toLowerCase().endsWith('.docx');
  item.status = 'busy';
  item.detail = isDocx
    ? 'Đang làm sạch metadata và ký tự ẩn (Lossless)…'
    : 'Đang tạo bản sạch…';
  render();
  try {
    const data = await api('/clean', item.file);
    item.result = { blob: fromBase64(data.cleaned, item.file.type), name: cleanedName(item.file.name), report: data.report };
    item.status = 'cleaned';
    const before = item.file.size, after = item.result.blob.size, delta = before - after;
    item.detail = 'Đang xác minh lại bản sạch…'; render();
    try {
      const verification = await api('/inspect', resultFile(item));
      item.detail = verification.suspicious?.verdict
        ? 'Đã làm sạch, nhưng vẫn còn dấu vết cần xem xét trong bản kết quả.'
        : isDocx
          ? `Đã làm sạch lossless và xác minh bảo toàn cấu trúc văn bản${delta > 0 ? ` · loại bỏ ${formatBytes(delta)} dữ liệu thừa` : ''}.`
          : `Đã xác minh sạch${delta > 0 ? ` · loại bỏ ${formatBytes(delta)} dữ liệu thừa` : ''}.`;
    } catch {
      item.detail = delta > 0 ? `Hoàn tất · đã loại bỏ ${formatBytes(delta)} dữ liệu thừa.` : 'Hoàn tất · chưa thể xác minh lại.';
    }
    if (!quiet) showToast(`${item.file.name} đã sẵn sàng tải xuống.`);
    return true;
  } catch (error) { item.status = 'error'; item.detail = error.message; return false; }
  finally { render(); }
}

function downloadItem(item) {
  if (!item.result) return;
  const url = URL.createObjectURL(item.result.blob); const link = document.createElement('a');
  link.href = url; link.download = item.result.name; document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function cleanAll() {
  els.cleanAll.disabled = true; els.clear.disabled = true;
  let done = 0;
  for (const item of state.files) if (await cleanItem(item, true)) done += 1;
  els.cleanAll.disabled = false; els.clear.disabled = false;
  showToast(`Đã làm sạch ${done}/${state.files.length} tệp.`);
}

async function checkServer() {
  els.server.className = 'server-state'; $('.server-state span:last-child').textContent = 'Đang kết nối';
  try {
    const response = await fetch('/health', { headers: state.apiKey ? { Authorization: `Bearer ${state.apiKey}` } : {} });
    if (response.status === 401) { els.server.classList.add('offline'); $('.server-state span:last-child').textContent = 'Cần khóa truy cập'; return; }
    if (!response.ok) throw new Error();
    const data = await response.json(); els.server.classList.add('online'); $('.server-state span:last-child').textContent = `Sẵn sàng · ${data.version}`;
  } catch { els.server.classList.add('offline'); $('.server-state span:last-child').textContent = 'Mất kết nối'; }
}

els.browse.onclick = () => els.input.click(); els.drop.onclick = event => { if (!event.target.closest('button')) els.input.click(); };
els.input.onchange = () => { addFiles(els.input.files); els.input.value = ''; };
for (const name of ['dragenter', 'dragover']) els.drop.addEventListener(name, event => { event.preventDefault(); els.drop.classList.add('dragging'); });
for (const name of ['dragleave', 'drop']) els.drop.addEventListener(name, event => { event.preventDefault(); els.drop.classList.remove('dragging'); });
els.drop.addEventListener('drop', event => addFiles(event.dataTransfer.files));
els.clear.onclick = () => { state.files = []; render(); }; els.cleanAll.onclick = cleanAll;
$('#settingsToggle').onclick = () => { els.key.value = state.apiKey; els.dialog.showModal(); };
$('#saveSettings').onclick = event => { event.preventDefault(); state.apiKey = els.key.value.trim(); if (state.apiKey) sessionStorage.setItem('clearmark-api-key', state.apiKey); else sessionStorage.removeItem('clearmark-api-key'); els.dialog.close(); checkServer(); };
checkServer();
