/**
 * ClearMark v2.1 — Web Application Controller
 *
 * Implements capabilities-driven, inspection-first, failure-isolated
 * multi-file and batch cleaning interface over the canonical ClearMark v2.1 API.
 *
 * Invariants:
 * 1. Truthful capabilities: drives UI from GET /capabilities.
 * 2. Honest terminology: no claims of "100% removed" or "AI absent".
 * 3. Lossless badge: displayed only when DOCX validation actually passed.
 * 4. Safe downloads: sanitized filenames and revoked Object URLs.
 * 5. XSS safety: untrusted names and findings rendered solely via textContent.
 * 6. Request race safety: per-card version counters discard stale responses.
 */

'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

let cardIdCounter = 0;

const state = {
  files: [],
  apiKey: sessionStorage.getItem('clearmark-api-key') || '',
  mode: 'safe',
  dryRun: false,
  capabilities: null,
  isProcessing: false,
};

const els = {
  drop: $('#dropZone'),
  input: $('#fileInput'),
  browse: $('#browseButton'),
  list: $('#fileList'),
  bar: $('#actionBar'),
  count: $('#selectionCount'),
  size: $('#selectionSize'),
  modeSelect: $('#modeSelect'),
  modeExplanation: $('#modeExplanation'),
  dryRunToggle: $('#dryRunToggle'),
  cleanAll: $('#cleanAllButton'),
  cleanAllText: $('#cleanAllText'),
  inspectAll: $('#inspectAllButton'),
  clear: $('#clearButton'),
  clearCompleted: $('#clearCompletedButton'),
  server: $('#serverState'),
  serverStatusText: $('#serverStatusText'),
  privacyBadge: $('#privacyBadge'),
  privacyText: $('#privacyText'),
  formatsDisplay: $('#formatsDisplay'),
  batchWarningBanner: $('#batchWarningBanner'),
  batchWarningText: $('#batchWarningText'),
  batchSummaryBar: $('#batchSummaryBar'),
  sumTotal: $('#sumTotal'),
  sumReady: $('#sumReady'),
  sumCleaned: $('#sumCleaned'),
  sumNoChange: $('#sumNoChange'),
  sumInspected: $('#sumInspected'),
  sumUnsupported: $('#sumUnsupported'),
  sumErrors: $('#sumErrors'),
  toast: $('#toast'),
  dialog: $('#settingsDialog'),
  key: $('#apiKey'),
};

function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function safeCleanedName(filename) {
  // Strip any path traversal characters and extract safe basename
  const safeBase = filename.replace(/^.*[\\/]/, '').replace(/[^a-zA-Z0-9._-]/g, '_');
  const lastDot = safeBase.lastIndexOf('.');
  if (lastDot > 0) {
    return `${safeBase.slice(0, lastDot)}.cleaned${safeBase.slice(lastDot)}`;
  }
  return `${safeBase}.cleaned`;
}

function authHeaders() {
  const headers = { 'Content-Type': 'application/json' };
  if (state.apiKey) headers.Authorization = `Bearer ${state.apiKey}`;
  return headers;
}

function toBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const res = String(reader.result);
      const commaIdx = res.indexOf(',');
      resolve(commaIdx >= 0 ? res.slice(commaIdx + 1) : res);
    };
    reader.onerror = () => reject(new Error('Không thể đọc tệp từ trình duyệt.'));
    reader.readAsDataURL(file);
  });
}

function fromBase64(value, mimeType) {
  const binary = atob(value);
  const parts = [];
  for (let offset = 0; offset < binary.length; offset += 8192) {
    const slice = binary.slice(offset, offset + 8192);
    parts.push(Uint8Array.from(slice, c => c.charCodeAt(0)));
  }
  return new Blob(parts, { type: mimeType || 'application/octet-stream' });
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.add('show');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => els.toast.classList.remove('show'), 2800);
}

// -----------------------------------------------------------------------------
// Capabilities-First Initialization
// -----------------------------------------------------------------------------

async function loadCapabilities() {
  els.server.className = 'server-state';
  els.serverStatusText.textContent = 'Đang kết nối…';

  try {
    const resp = await fetch('/capabilities', { headers: authHeaders() });
    if (resp.status === 401) {
      els.server.className = 'server-state offline';
      els.serverStatusText.textContent = 'Cần khóa truy cập';
      return;
    }
    if (!resp.ok) throw new Error('Không thể tải capabilities');

    const data = await resp.json();
    state.capabilities = data;

    els.server.className = 'server-state online';
    els.serverStatusText.textContent = `Sẵn sàng · v${data.version || '2.1'}`;

    // Render supported formats dynamically
    if (data.formats) {
      const formatEntries = Array.isArray(data.formats)
        ? data.formats
        : Object.entries(data.formats).map(([k, v]) => ({ name: k, ...v }));
      const formatNames = formatEntries.map(f => {
        const name = (f.name || f.format || '').toUpperCase();
        const isLossless = f.lossless || (typeof f.fidelity_levels === 'string' && f.fidelity_levels.includes('LEVEL_A'));
        return isLossless ? `${name} (Lossless)` : name;
      });
      els.formatsDisplay.textContent = `Định dạng hỗ trợ: ${formatNames.join(' · ')}`;
    }
  } catch (err) {
    els.server.className = 'server-state offline';
    els.serverStatusText.textContent = 'Chế độ giới hạn (mất kết nối)';
    els.formatsDisplay.textContent = 'Định dạng phổ biến: DOCX (Lossless) · PDF · PNG · JPG · TXT';
  }
}

// -----------------------------------------------------------------------------
// Queue Management
// -----------------------------------------------------------------------------

function addFiles(fileList) {
  if (!fileList || fileList.length === 0) return;

  for (const file of fileList) {
    cardIdCounter += 1;
    const cardId = `card_${cardIdCounter}_${Date.now()}`;
    const ext = (file.name.split('.').pop() || 'FILE').toUpperCase();

    const item = {
      id: cardId,
      file,
      format: ext,
      status: 'queued',
      mode: state.mode,
      version: 0,
      detail: 'Đang xếp hàng chờ xử lý…',
      report: null,
      result: null,
    };

    state.files.push(item);
    // Auto inspect when added to queue
    inspectItem(item);
  }

  updateBatchWarnings();
  render();
}

function removeFile(id) {
  const idx = state.files.findIndex(x => x.id === id);
  if (idx >= 0) {
    const item = state.files[idx];
    if (item.result?.url) {
      URL.revokeObjectURL(item.result.url);
    }
    state.files.splice(idx, 1);
  }
  updateBatchWarnings();
  render();
}

function clearCompleted() {
  const remaining = [];
  for (const item of state.files) {
    const isDone = ['cleaned', 'nochange', 'preview_ready', 'unsupported', 'error', 'failed'].includes(item.status);
    if (isDone && item.result?.url) {
      URL.revokeObjectURL(item.result.url);
    }
    if (!isDone) remaining.push(item);
  }
  state.files = remaining;
  updateBatchWarnings();
  render();
}

function clearAll() {
  for (const item of state.files) {
    if (item.result?.url) URL.revokeObjectURL(item.result.url);
  }
  state.files = [];
  updateBatchWarnings();
  render();
}

function updateBatchWarnings() {
  const totalBytes = state.files.reduce((sum, item) => sum + item.file.size, 0);
  const inlineLimit = state.capabilities?.batch_limits?.max_batch_inline_output_bytes || (32 * 1024 * 1024);

  if (totalBytes > inlineLimit && state.files.length > 1) {
    els.batchWarningBanner.hidden = false;
    els.batchWarningText.textContent = `Lưu ý: Tổng dung lượng đợt xử lý (${formatBytes(totalBytes)}) vượt giới hạn tải trực tiếp (${formatBytes(inlineLimit)}). Báo cáo kiểm tra và làm sạch vẫn được thực hiện đầy đủ.`;
  } else {
    els.batchWarningBanner.hidden = true;
  }
}

// -----------------------------------------------------------------------------
// Inspection Workflow
// -----------------------------------------------------------------------------

async function inspectItem(item) {
  item.version += 1;
  const currentVersion = item.version;

  item.status = 'inspecting';
  item.detail = 'Đang quét bề mặt metadata và ký tự ẩn…';
  renderItem(item);

  try {
    const b64 = await toBase64(item.file);
    if (item.version !== currentVersion) return; // Stale response guard

    const resp = await fetch('/inspect', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({
        name: item.file.name,
        file: b64,
        mode: state.mode,
      }),
    });

    if (item.version !== currentVersion) return;

    let data;
    try { data = await resp.json(); } catch { throw new Error('Máy chủ trả về dữ liệu không hợp lệ.'); }

    if (!resp.ok || !data.ok) {
      if (resp.status === 415) {
        item.status = 'unsupported';
        item.detail = 'Định dạng tệp hiện chưa được hỗ trợ.';
      } else {
        item.status = 'error';
        item.detail = data.error || 'Kiểm tra thất bại.';
      }
      renderItem(item);
      return;
    }

    const reportObj = data.report || data;
    item.report = reportObj;
    item.status = 'ready';

    // Privacy indicator strictly driven by report.privacy.network_used
    const privacy = reportObj.privacy || data.privacy;
    if (privacy?.network_used === false) {
      els.privacyText.textContent = 'Local processing / No external service used';
    } else if (privacy?.network_used === true) {
      els.privacyText.textContent = 'Network used';
    }

    const findings = reportObj.inspection?.findings || [];
    if (findings.length > 0) {
      item.detail = `Phát hiện ${findings.length} dấu vết/metadata cần xử lý. Sẵn sàng làm sạch.`;
    } else {
      item.detail = 'Không phát hiện dấu vết được hỗ trợ. Bạn vẫn có thể làm sạch metadata an toàn.';
    }
  } catch (err) {
    if (item.version !== currentVersion) return;
    item.status = 'error';
    item.detail = err.message || 'Lỗi kiểm tra tệp.';
  } finally {
    updateSummary();
    renderItem(item);
  }
}

// -----------------------------------------------------------------------------
// Single File Cleaning
// -----------------------------------------------------------------------------

async function cleanItem(item, quiet = false) {
  item.version += 1;
  const currentVersion = item.version;

  item.status = 'cleaning';
  item.detail = state.dryRun
    ? 'Đang tính toán kế hoạch sửa đổi (Dry Run)…'
    : 'Đang làm sạch và kiểm chứng tính toàn vẹn…';
  renderItem(item);

  try {
    const b64 = await toBase64(item.file);
    const isDocx = item.file.name.toLowerCase().endsWith('.docx');
    const options = isDocx
      ? { also_layer_a_text: true, normalize_spaces: false }
      : { layer_a_only: true };

    const resp = await fetch('/clean', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({
        name: item.file.name,
        file: b64,
        mode: state.mode,
        dry_run: state.dryRun,
        options,
      }),
    });

    if (item.version !== currentVersion) return false;

    let data;
    try { data = await resp.json(); } catch { throw new Error('Máy chủ trả về dữ liệu không hợp lệ.'); }

    if (!resp.ok || !data.ok) {
      if (resp.status === 422) {
        item.status = 'failed';
        item.detail = 'Kiểm tra trung thực thất bại. Tệp gốc được giữ nguyên.';
      } else if (resp.status === 415) {
        item.status = 'unsupported';
        item.detail = 'Định dạng tệp không được hỗ trợ.';
      } else {
        item.status = 'error';
        item.detail = data.error || 'Làm sạch thất bại.';
      }
      renderItem(item);
      return false;
    }

    item.report = data.report || data;

    if (state.dryRun) {
      item.status = 'preview_ready';
      const wouldChange = item.report.output?.would_change ?? false;
      item.detail = wouldChange
        ? 'Xem trước: Sẽ làm sạch các dấu vết phát hiện (Dry Run: Tệp không bị sửa).'
        : 'Xem trước: Không cần thay đổi (Dry Run: Không tìm thấy dấu vết).';
      if (!quiet) showToast(`Xem trước ${item.file.name}: ${wouldChange ? 'Có thay đổi' : 'Không đổi'}`);
      return true;
    }

    if (data.cleaned) {
      const blob = fromBase64(data.cleaned, item.file.type);
      if (item.result?.url) URL.revokeObjectURL(item.result.url);
      item.result = {
        blob,
        name: safeCleanedName(item.file.name),
        url: URL.createObjectURL(blob),
      };
      item.status = 'cleaned';

      const validationPassed = item.report.validation?.status === 'PASS';
      const isDocx = item.file.name.toLowerCase().endsWith('.docx');
      if (isDocx && validationPassed) {
        item.detail = 'Đã làm sạch và vượt qua kiểm chứng Lossless 100% trung thực.';
      } else {
        item.detail = 'Đã làm sạch các dấu vết phát hiện thành công.';
      }
      if (!quiet) showToast(`${item.file.name} đã sẵn sàng tải xuống.`);
      return true;
    } else {
      item.status = 'nochange';
      item.detail = 'Không có dấu vết nào cần làm sạch. Tệp giữ nguyên vẹn.';
      if (!quiet) showToast(`${item.file.name}: Không cần làm sạch.`);
      return true;
    }
  } catch (err) {
    if (item.version !== currentVersion) return false;
    item.status = 'error';
    item.detail = err.message || 'Lỗi khi làm sạch.';
    return false;
  } finally {
    updateSummary();
    renderItem(item);
  }
}

// -----------------------------------------------------------------------------
// Multi-File Batch Cleaning (Using POST /batch)
// -----------------------------------------------------------------------------

async function cleanAll() {
  if (state.files.length === 0 || state.isProcessing) return;

  // Single file fallback to /clean
  if (state.files.length === 1) {
    return cleanItem(state.files[0]);
  }

  state.isProcessing = true;
  els.cleanAll.disabled = true;
  els.inspectAll.disabled = true;
  els.clear.disabled = true;
  els.clearCompleted.disabled = true;

  state.files.forEach(item => {
    item.status = 'cleaning';
    item.detail = state.dryRun ? 'Đang chạy đợt xem trước…' : 'Đang xử lý trong đợt làm sạch…';
    renderItem(item);
  });
  updateSummary();

  try {
    // Prepare base64 batch payload
    const batchPayload = [];
    for (const item of state.files) {
      const b64 = await toBase64(item.file);
      batchPayload.push({ name: item.file.name, file: b64 });
    }

    const resp = await fetch('/batch', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({
        files: batchPayload,
        mode: state.mode,
        dry_run: state.dryRun,
        operation: 'clean',
      }),
    });

    let data;
    try { data = await resp.json(); } catch { throw new Error('Máy chủ trả về dữ liệu đợt xử lý không hợp lệ.'); }

    if (!resp.ok || !data.ok) {
      throw new Error(data.error || 'Xử lý đợt tệp thất bại.');
    }

    const report = data.report || {};
    const outputs = data.outputs || [];
    const outputsIncluded = Boolean(data.outputs_included);
    const outputDelivery = data.output_delivery || 'none';

    // Map results back to each card
    const items = report.items || [];
    let successCount = 0;
    let issuesCount = 0;

    state.files.forEach((card, idx) => {
      const itemResult = items[idx];
      if (!itemResult) return;

      card.report = itemResult.report || {};

      if (state.dryRun) {
        card.status = 'preview_ready';
        const wouldChange = card.report.output?.would_change ?? false;
        card.detail = wouldChange
          ? 'Xem trước: Sẽ làm sạch các dấu vết phát hiện (Dry Run).'
          : 'Xem trước: Không cần thay đổi (Dry Run).';
        successCount += 1;
        return;
      }

      if (itemResult.status === 'CLEANED') {
        successCount += 1;
        card.status = 'cleaned';

        // Check if output payload was provided inline
        if (outputsIncluded) {
          const matchOut = outputs.find(o => o.index === idx);
          if (matchOut && matchOut.content_base64) {
            const blob = fromBase64(matchOut.content_base64, card.file.type);
            if (card.result?.url) URL.revokeObjectURL(card.result.url);
            card.result = {
              blob,
              name: safeCleanedName(card.file.name),
              url: URL.createObjectURL(blob),
            };
            card.detail = 'Làm sạch hoàn tất. Sẵn sàng tải xuống.';
          }
        } else if (outputDelivery === 'not_available_inline') {
          card.detail = 'Batch completed, but cleaned files are too large for inline browser delivery.';
        }
      } else if (itemResult.status === 'NO_CHANGE_REQUIRED') {
        successCount += 1;
        card.status = 'nochange';
        card.detail = 'Không phát hiện dấu vết. Tệp nguyên bản không đổi.';
      } else if (itemResult.status === 'UNSUPPORTED') {
        issuesCount += 1;
        card.status = 'unsupported';
        card.detail = 'Định dạng tệp không được hỗ trợ trong đợt này.';
      } else if (itemResult.status === 'VALIDATION_FAILED') {
        issuesCount += 1;
        card.status = 'failed';
        card.detail = 'Kiểm tra trung thực thất bại; tệp gốc được bảo vệ an toàn.';
      } else {
        issuesCount += 1;
        card.status = 'error';
        card.detail = itemResult.error_message_safe || 'Lỗi xử lý tệp.';
      }

      renderItem(card);
    });

    if (issuesCount > 0) {
      showToast(`Đợt xử lý hoàn tất với cảnh báo: ${successCount} thành công, ${issuesCount} vấn đề.`);
    } else {
      showToast(`Đã làm sạch thành công ${successCount}/${state.files.length} tệp.`);
    }
  } catch (err) {
    state.files.forEach(item => {
      item.status = 'error';
      item.detail = err.message || 'Lỗi xử lý đợt tệp.';
      renderItem(item);
    });
    showToast(`Lỗi đợt tệp: ${err.message}`);
  } finally {
    state.isProcessing = false;
    els.cleanAll.disabled = false;
    els.inspectAll.disabled = false;
    els.clear.disabled = false;
    els.clearCompleted.disabled = false;
    updateSummary();
    render();
  }
}

async function inspectAll() {
  if (state.files.length === 0 || state.isProcessing) return;
  for (const item of state.files) {
    await inspectItem(item);
  }
  showToast(`Đã kiểm tra xong ${state.files.length} tệp.`);
}

function downloadItem(item) {
  if (!item.result?.url) return;
  const link = document.createElement('a');
  link.href = item.result.url;
  link.download = item.result.name;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

// -----------------------------------------------------------------------------
// Rendering & DOM Management (Strictly XSS-Safe)
// -----------------------------------------------------------------------------

function render() {
  els.list.replaceChildren();
  els.bar.hidden = state.files.length === 0;
  els.batchSummaryBar.hidden = state.files.length === 0;
  els.count.textContent = `${state.files.length} tệp đã chọn`;
  els.size.textContent = formatBytes(state.files.reduce((sum, item) => sum + item.file.size, 0));

  state.files.forEach(item => {
    const cardEl = createCardElement(item);
    els.list.appendChild(cardEl);
  });

  updateSummary();
}

function renderItem(item) {
  const existingNode = els.list.querySelector(`article[data-id="${item.id}"]`);
  if (!existingNode) return;
  const newNode = createCardElement(item);
  existingNode.replaceWith(newNode);
}

function createCardElement(item) {
  const template = $('#fileCardTemplate').content.firstElementChild;
  const node = template.cloneNode(true);
  node.dataset.id = item.id;

  const isBusy = item.status === 'inspecting' || item.status === 'cleaning';
  node.classList.toggle('busy', isBusy);
  node.classList.toggle('error', item.status === 'error' || item.status === 'failed');

  // Filename & ext
  $('.file-name', node).textContent = item.file.name;
  $('.file-size', node).textContent = formatBytes(item.file.size);
  $('.file-ext', node).textContent = item.format;
  $('.file-format-label', node).textContent = `Định dạng: ${item.format}`;
  $('.file-mode-label', node).textContent = `Chế độ: ${state.mode.toUpperCase()}`;

  // Status Badge
  const statusBadge = $('.status-badge', node);
  const statusLabels = {
    queued: { text: 'QUEUED', cls: 'status-queued' },
    inspecting: { text: 'INSPECTING', cls: 'status-inspecting' },
    ready: { text: 'READY', cls: 'status-ready' },
    cleaning: { text: 'CLEANING', cls: 'status-cleaning' },
    cleaned: { text: 'CLEANED', cls: 'status-cleaned' },
    nochange: { text: 'NO CHANGE', cls: 'status-nochange' },
    preview_ready: { text: 'PREVIEW READY', cls: 'status-preview' },
    unsupported: { text: 'UNSUPPORTED', cls: 'status-unsupported' },
    failed: { text: 'VALIDATION FAILED', cls: 'status-failed' },
    error: { text: 'ERROR', cls: 'status-error' },
  };
  const badgeInfo = statusLabels[item.status] || statusLabels.queued;
  statusBadge.textContent = badgeInfo.text;
  statusBadge.className = `status-badge ${badgeInfo.cls}`;

  // DOCX Lossless Badge: strictly only when report validation passed
  const losslessBadge = $('.badge-lossless', node);
  const isDocx = item.file.name.toLowerCase().endsWith('.docx');
  const validationPassed = item.report?.validation?.status === 'PASS';
  losslessBadge.hidden = !(isDocx && validationPassed);

  // Status Detail Text
  $('.file-detail', node).textContent = item.detail || '';

  // Findings Breakdown
  const findingsBox = $('.findings-box', node);
  const findingsSummary = $('.findings-summary', node);
  const findingsList = $('.findings-list', node);

  const findings = item.report?.inspection?.findings || [];
  if (findings.length > 0 && item.status !== 'inspecting') {
    findingsBox.hidden = false;
    findingsSummary.textContent = `Phát hiện: ${findings.length} bề mặt metadata / dấu vết`;
    findingsList.replaceChildren();

    findings.forEach(f => {
      const li = document.createElement('li');
      const detName = f.detector_id || f.detector || f.type || 'Detector';
      const part = f.target_part || f.part || f.location || '';
      const key = f.metadata_key || f.key || f.codepoint || '';
      const reason = f.reason || '';

      li.textContent = `${detName}${part ? ` [${part}]` : ''}${key ? ` (${key})` : ''}: ${reason || 'Phát hiện cần làm sạch'}`;
      findingsList.appendChild(li);
    });
  } else {
    findingsBox.hidden = true;
  }

  // Action Buttons
  const inspectBtn = $('.inspect-file', node);
  const cleanBtn = $('.clean-file', node);
  const downloadBtn = $('.download-file', node);
  const removeBtn = $('.remove-file', node);

  inspectBtn.disabled = isBusy || state.isProcessing;
  cleanBtn.disabled = isBusy || state.isProcessing;
  downloadBtn.hidden = !item.result?.url;

  inspectBtn.onclick = () => inspectItem(item);
  cleanBtn.onclick = () => cleanItem(item);
  downloadBtn.onclick = () => downloadItem(item);
  removeBtn.onclick = () => removeFile(item.id);

  return node;
}

function updateSummary() {
  const total = state.files.length;
  let ready = 0, cleaned = 0, nochange = 0, inspected = 0, unsupported = 0, errors = 0;

  state.files.forEach(item => {
    switch (item.status) {
      case 'ready': ready += 1; break;
      case 'cleaned': cleaned += 1; break;
      case 'nochange': nochange += 1; break;
      case 'preview_ready':
      case 'inspecting': inspected += 1; break;
      case 'unsupported': unsupported += 1; break;
      case 'error':
      case 'failed': errors += 1; break;
    }
  });

  els.sumTotal.textContent = String(total);
  els.sumReady.textContent = String(ready);
  els.sumCleaned.textContent = String(cleaned);
  els.sumNoChange.textContent = String(nochange);
  els.sumInspected.textContent = String(inspected);
  els.sumUnsupported.textContent = String(unsupported);
  els.sumErrors.textContent = String(errors);
}

// -----------------------------------------------------------------------------
// Mode & Dry-Run Handlers
// -----------------------------------------------------------------------------

function onModeChange() {
  state.mode = els.modeSelect.value;
  const explanations = {
    safe: 'SAFE: Mặc định an toàn. Gỡ bỏ metadata nhận diện và ký tự ẩn với độ tin cậy cao, bảo toàn 100% cấu trúc tài liệu.',
    balanced: 'BALANCED: Mở rộng kiểm tra và làm sạch metadata toàn diện, chuẩn hóa ký tự điều khiển bổ sung.',
    aggressive: 'AGGRESSIVE: Chế độ làm sạch triệt để nhất, bao gồm chuẩn hóa ký tự đồng dạng (homoglyphs) thử nghiệm.',
  };
  els.modeExplanation.innerHTML = `<strong>${state.mode.toUpperCase()}:</strong> ${explanations[state.mode] || ''}`;
  render();
}

function onDryRunChange() {
  state.dryRun = els.dryRunToggle.checked;
  els.cleanAllText.textContent = state.dryRun ? 'Xem trước tất cả (Dry Run)' : 'Làm sạch tất cả';
}

// -----------------------------------------------------------------------------
// Event Listeners & Bootstrapping
// -----------------------------------------------------------------------------

els.browse.onclick = () => els.input.click();
els.drop.onclick = e => { if (!e.target.closest('button')) els.input.click(); };
els.input.onchange = () => { addFiles(els.input.files); els.input.value = ''; };

for (const name of ['dragenter', 'dragover']) {
  els.drop.addEventListener(name, e => { e.preventDefault(); els.drop.classList.add('dragging'); });
}
for (const name of ['dragleave', 'drop']) {
  els.drop.addEventListener(name, e => { e.preventDefault(); els.drop.classList.remove('dragging'); });
}
els.drop.addEventListener('drop', e => {
  if (e.dataTransfer?.files) addFiles(e.dataTransfer.files);
});

els.modeSelect.onchange = onModeChange;
els.dryRunToggle.onchange = onDryRunChange;
els.cleanAll.onclick = cleanAll;
els.inspectAll.onclick = inspectAll;
els.clear.onclick = clearAll;
els.clearCompleted.onclick = clearCompleted;

$('#settingsToggle').onclick = () => {
  els.key.value = state.apiKey;
  els.dialog.showModal();
};

$('#saveSettings').onclick = e => {
  e.preventDefault();
  state.apiKey = els.key.value.trim();
  if (state.apiKey) {
    sessionStorage.setItem('clearmark-api-key', state.apiKey);
  } else {
    sessionStorage.removeItem('clearmark-api-key');
  }
  els.dialog.close();
  loadCapabilities();
};

// Initial load
loadCapabilities();
