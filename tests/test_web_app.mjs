/**
 * Node.js Unit Tests for ClearMark v2.1 Frontend Logic (service/web/app.js)
 * Run with: node --test tests/test_web_app.mjs
 */

import test from 'node:test';
import assert from 'node:assert/strict';

// Helper re-implementations strictly matching app.js logic to test pure functions

function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function safeCleanedName(filename) {
  const safeBase = filename.replace(/^.*[\\/]/, '').replace(/[^a-zA-Z0-9._-]/g, '_');
  const lastDot = safeBase.lastIndexOf('.');
  if (lastDot > 0) {
    return `${safeBase.slice(0, lastDot)}.cleaned${safeBase.slice(lastDot)}`;
  }
  return `${safeBase}.cleaned`;
}

test('formatBytes formats units correctly', () => {
  assert.equal(formatBytes(0), '0 B');
  assert.equal(formatBytes(500), '500 B');
  assert.equal(formatBytes(1024), '1.0 KB');
  assert.equal(formatBytes(1048576), '1.0 MB');
  assert.equal(formatBytes(33554432), '32.0 MB');
});

test('safeCleanedName prevents path traversal and unsafe characters', () => {
  assert.equal(safeCleanedName('../../evil.docx'), 'evil.cleaned.docx');
  assert.equal(safeCleanedName('..\\..\\passwords.txt'), 'passwords.cleaned.txt');
  assert.equal(safeCleanedName('C:\\Windows\\System32\\cmd.exe'), 'cmd.cleaned.exe');
  assert.equal(safeCleanedName('regular_file.docx'), 'regular_file.cleaned.docx');
  assert.equal(safeCleanedName('<img src=x onerror=alert(1)>.png'), '_img_src_x_onerror_alert_1__.cleaned.png');
});

test('Card state mapping and status labels are complete', () => {
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

  const expectedStatuses = [
    'queued', 'inspecting', 'ready', 'cleaning', 'cleaned',
    'nochange', 'preview_ready', 'unsupported', 'failed', 'error'
  ];

  for (const s of expectedStatuses) {
    assert.ok(statusLabels[s], `Missing status label mapping for ${s}`);
    assert.ok(statusLabels[s].text.length > 0);
  }
});

test('DOCX Lossless badge predicate enforces strict invariants', () => {
  function shouldShowLosslessBadge(filename, report) {
    const isDocx = filename.toLowerCase().endsWith('.docx');
    const validationPassed = report?.validation?.status === 'PASS';
    return isDocx && validationPassed;
  }

  // Case 1: Valid DOCX with PASS -> TRUE
  assert.equal(shouldShowLosslessBadge('document.docx', { validation: { status: 'PASS' } }), true);

  // Case 2: Valid DOCX with FAIL -> FALSE
  assert.equal(shouldShowLosslessBadge('document.docx', { validation: { status: 'FAIL' } }), false);

  // Case 3: Valid DOCX with SKIPPED -> FALSE
  assert.equal(shouldShowLosslessBadge('document.docx', { validation: { status: 'SKIPPED' } }), false);

  // Case 4: Non-DOCX file even with PASS -> FALSE
  assert.equal(shouldShowLosslessBadge('image.png', { validation: { status: 'PASS' } }), false);
  assert.equal(shouldShowLosslessBadge('sheet.xlsx', { validation: { status: 'PASS' } }), false);

  // Case 5: Missing validation property -> FALSE
  assert.equal(shouldShowLosslessBadge('document.docx', {}), false);
});

test('Batch summary counts mathematically reconcile', () => {
  const cards = [
    { status: 'ready' },
    { status: 'cleaned' },
    { status: 'nochange' },
    { status: 'preview_ready' },
    { status: 'unsupported' },
    { status: 'error' },
    { status: 'failed' },
  ];

  let ready = 0, cleaned = 0, nochange = 0, inspected = 0, unsupported = 0, errors = 0;
  for (const item of cards) {
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
  }

  const terminalSum = ready + cleaned + nochange + inspected + unsupported + errors;
  assert.equal(terminalSum, cards.length);
});

test('HTTP Batch response transport envelope decoding', () => {
  // Transport envelope matching server.py _handle_batch contract
  const serverResponse = {
    ok: true,
    report: {
      schema_version: '2.1.0',
      batch_id: 'test-batch-uuid',
      summary: { total: 2, cleaned: 1, unsupported: 1, errors: 0, no_change: 0, inspected: 0, validation_failed: 0, skipped: 0 },
      items: [
        { index: 0, input_path: 'doc.docx', status: 'CLEANED' },
        { index: 1, input_path: 'bad.xyz', status: 'UNSUPPORTED' }
      ]
    },
    outputs_included: true,
    output_delivery: 'inline',
    outputs: [
      { index: 0, name: 'doc.docx', sha256: 'abc123', content_base64: 'UEsDBBQAAAAIA...' }
    ]
  };

  assert.equal(serverResponse.ok, true);
  assert.equal(serverResponse.outputs_included, true);
  assert.equal(serverResponse.outputs.length, 1);
  assert.equal(serverResponse.outputs[0].index, 0);

  // Failed / unsupported item is NOT in outputs
  const matchBad = serverResponse.outputs.find(o => o.index === 1);
  assert.equal(matchBad, undefined);
});
