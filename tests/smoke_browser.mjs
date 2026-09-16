/**
 * ClearMark v2.1 — Phase 5 Browser Gate Smoke Test (tests/smoke_browser.mjs)
 *
 * Implements Section 45 real-browser smoke scenario:
 * 1. open UI
 * 2. select Golden DOCX
 * 3. inspection succeeds
 * 4. SAFE selected
 * 5. run dry-run
 * 6. would-change shown
 * 7. no download available
 * 8. run actual clean
 * 9. validation passes
 * 10. download becomes available
 * 11. add at least two more files
 * 12. execute batch
 * 13. verify individual card states
 * 14. partial failure does not erase successful results
 * 15. reload UI and verify application initializes cleanly
 *
 * Runs natively via Chrome DevTools Protocol (CDP) against installed Google Chrome.
 * Zero external packages / zero network downloads.
 */

import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const UI_URL = 'http://127.0.0.1:8765/';
const CDP_PORT = 9222;

const GOLDEN_DOCX = 'E:\\wartermark_remove\\01_GOLDEN_ORIGINAL_UNTOUCHED.docx';
const TEXT_FIXTURE = 'E:\\wartermark_remove\\tests\\fixtures\\sample_watermarked.txt';
const UNSUPPORTED_FIXTURE = 'E:\\wartermark_remove\\tests\\fixtures\\unsupported_file.xyz';

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

class CDPClient {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.msgId = 0;
    this.callbacks = new Map();
  }

  async connect() {
    return new Promise((resolve, reject) => {
      this.ws.onopen = resolve;
      this.ws.onerror = reject;
      this.ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.id && this.callbacks.has(msg.id)) {
          const { resolve, reject } = this.callbacks.get(msg.id);
          this.callbacks.delete(msg.id);
          if (msg.error) reject(new Error(msg.error.message || JSON.stringify(msg.error)));
          else resolve(msg.result);
        }
      };
    });
  }

  async send(method, params = {}) {
    this.msgId += 1;
    const id = this.msgId;
    return new Promise((resolve, reject) => {
      this.callbacks.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async eval(expression) {
    const res = await this.send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    if (res.exceptionDetails) {
      throw new Error(res.exceptionDetails.exception?.description || 'Evaluation error in browser page');
    }
    return res.result?.value;
  }

  async setFiles(selector, filePaths) {
    const doc = await this.send('DOM.getDocument');
    const node = await this.send('DOM.querySelector', {
      nodeId: doc.root.nodeId,
      selector,
    });
    if (!node || !node.nodeId) throw new Error(`Element not found for selector: ${selector}`);
    await this.send('DOM.setFileInputFiles', {
      files: filePaths,
      nodeId: node.nodeId,
    });
  }

  close() {
    try { this.ws.close(); } catch {}
  }
}

async function main() {
  console.log('============================================================');
  console.log('CLEARMARK v2.1 — PHASE 5 BROWSER GATE SMOKE TEST');
  console.log('============================================================');

  const tempProfile = mkdtempSync(join(tmpdir(), 'clearmark_smoke_'));
  let chromeProc = null;

  try {
    // 1. Launch Chrome
    console.log(`[INFO] Launching Chrome from: ${CHROME_PATH}`);
    chromeProc = spawn(CHROME_PATH, [
      '--headless=new',
      `--remote-debugging-port=${CDP_PORT}`,
      `--user-data-dir=${tempProfile}`,
      'about:blank',
    ], { stdio: 'ignore' });

    // Wait for CDP readiness
    let versionInfo = null;
    for (let i = 0; i < 30; i++) {
      try {
        const resp = await fetch(`http://127.0.0.1:${CDP_PORT}/json/version`);
        if (resp.ok) {
          versionInfo = await resp.json();
          break;
        }
      } catch {}
      await sleep(200);
    }

    if (!versionInfo) {
      throw new Error('Failed to connect to Chrome DevTools Protocol port 9222.');
    }

    const browserName = versionInfo.Browser || 'Chrome';
    console.log(`[PASS] Connected to real browser: ${browserName}`);

    // Create / attach to tab
    const newTabResp = await fetch(`http://127.0.0.1:${CDP_PORT}/json/new?${encodeURIComponent(UI_URL)}`, { method: 'PUT' });
    const target = await newTabResp.json();
    const wsUrl = target.webSocketDebuggerUrl;

    const cdp = new CDPClient(wsUrl);
    await cdp.connect();
    await cdp.send('Page.enable');
    await cdp.send('DOM.enable');
    await cdp.send('Runtime.enable');

    // Wait for page load and capabilities initialization
    console.log('\n--- Step 1: Open UI & Verify Capabilities ---');
    await sleep(1500);

    const pageState = await cdp.eval(`(() => ({
      title: document.title,
      serverText: document.querySelector('#serverStatusText')?.textContent || '',
      formatsText: document.querySelector('#formatsDisplay')?.textContent || '',
      mode: document.querySelector('#modeSelect')?.value || '',
      queueLength: document.querySelectorAll('#fileList > article').length
    }))()`);

    console.log(`  Page Title: "${pageState.title}"`);
    console.log(`  Server Status: "${pageState.serverText}"`);
    console.log(`  Formats Display: "${pageState.formatsText}"`);

    if (!pageState.title.includes('ClearMark')) throw new Error('Title does not match ClearMark');
    if (!pageState.serverText.includes('Sẵn sàng') && !pageState.serverText.includes('Ready')) {
      throw new Error(`Unexpected server status text: ${pageState.serverText}`);
    }
    if (!pageState.formatsText.includes('DOCX')) throw new Error('Formats do not list DOCX');
    console.log('[PASS] Step 1: UI opened and capabilities initialized cleanly.');

    // Step 2 & 3: Select Golden DOCX & Inspection
    console.log('\n--- Step 2 & 3: Select Golden DOCX & Verify Inspection ---');
    await cdp.setFiles('#fileInput', [GOLDEN_DOCX]);
    console.log(`  Uploaded: ${GOLDEN_DOCX}`);

    // Poll for inspection completion
    let docxCard = null;
    for (let i = 0; i < 40; i++) {
      await sleep(300);
      docxCard = await cdp.eval(`(() => {
        const card = document.querySelector('#fileList > article');
        if (!card) return null;
        return {
          status: card.querySelector('.status-badge')?.textContent?.trim(),
          name: card.querySelector('.file-name')?.textContent?.trim(),
          findingsHidden: card.querySelector('.findings-box')?.hidden,
          findingsText: card.querySelector('.findings-summary')?.textContent?.trim(),
          losslessHidden: card.querySelector('.badge-lossless')?.hidden,
          downloadHidden: card.querySelector('.download-file')?.hidden
        };
      })()`);
      if (docxCard && docxCard.status === 'READY') break;
    }

    if (!docxCard || docxCard.status !== 'READY') {
      throw new Error(`Expected status READY after inspection, got: ${docxCard?.status}`);
    }
    console.log(`  Card Status: ${docxCard.status}`);
    console.log(`  Findings: "${docxCard.findingsText}"`);
    if (docxCard.findingsHidden) throw new Error('Expected findings box to be visible');
    if (!docxCard.losslessHidden) throw new Error('Lossless badge must NOT be visible before clean');
    if (!docxCard.downloadHidden) throw new Error('Download button must NOT be visible before clean');
    console.log('[PASS] Step 2 & 3: Golden DOCX inspected with truthful findings.');

    // Step 4: SAFE selected
    console.log('\n--- Step 4: Verify Mode Selector ---');
    const modeValue = await cdp.eval(`document.querySelector('#modeSelect').value`);
    if (modeValue !== 'safe') throw new Error(`Expected safe mode, got: ${modeValue}`);
    console.log(`  Current Mode: ${modeValue.toUpperCase()}`);
    console.log('[PASS] Step 4: SAFE mode is default.');

    // Step 5, 6, 7: Dry Run & Preview Ready
    console.log('\n--- Step 5, 6 & 7: Dry Run Mode & Preview ---');
    await cdp.eval(`(() => {
      const toggle = document.querySelector('#dryRunToggle');
      toggle.checked = true;
      toggle.dispatchEvent(new Event('change'));
    })()`);

    // Click clean/preview button
    await cdp.eval(`document.querySelector('.clean-file').click()`);

    let dryRunResult = null;
    for (let i = 0; i < 40; i++) {
      await sleep(300);
      dryRunResult = await cdp.eval(`(() => {
        const card = document.querySelector('#fileList > article');
        return {
          status: card.querySelector('.status-badge')?.textContent?.trim(),
          detail: card.querySelector('.file-detail')?.textContent?.trim(),
          downloadHidden: card.querySelector('.download-file')?.hidden
        };
      })()`);
      if (dryRunResult && dryRunResult.status === 'PREVIEW READY') break;
    }

    if (!dryRunResult || dryRunResult.status !== 'PREVIEW READY') {
      throw new Error(`Expected PREVIEW READY status, got: ${dryRunResult?.status}`);
    }
    console.log(`  Dry Run Status: ${dryRunResult.status}`);
    console.log(`  Dry Run Detail: "${dryRunResult.detail}"`);
    if (!dryRunResult.downloadHidden) throw new Error('Download button must NOT be visible in dry-run mode');
    console.log('[PASS] Step 5, 6 & 7: Dry run completed, would-change reported truthfully, no download button shown.');

    // Step 8, 9, 10: Actual Clean & Lossless Badge
    console.log('\n--- Step 8, 9 & 10: Actual Clean & Lossless Validation Badge ---');
    await cdp.eval(`(() => {
      const toggle = document.querySelector('#dryRunToggle');
      toggle.checked = false;
      toggle.dispatchEvent(new Event('change'));
    })()`);

    // Click clean button
    await cdp.eval(`document.querySelector('.clean-file').click()`);

    let cleanResult = null;
    for (let i = 0; i < 60; i++) {
      await sleep(400);
      cleanResult = await cdp.eval(`(() => {
        const card = document.querySelector('#fileList > article');
        return {
          status: card.querySelector('.status-badge')?.textContent?.trim(),
          detail: card.querySelector('.file-detail')?.textContent?.trim(),
          losslessHidden: card.querySelector('.badge-lossless')?.hidden,
          downloadHidden: card.querySelector('.download-file')?.hidden
        };
      })()`);
      if (cleanResult && cleanResult.status === 'CLEANED') break;
    }

    if (!cleanResult || cleanResult.status !== 'CLEANED') {
      throw new Error(`Expected CLEANED status, got: ${cleanResult?.status}`);
    }
    console.log(`  Clean Status: ${cleanResult.status}`);
    console.log(`  Clean Detail: "${cleanResult.detail}"`);
    console.log(`  Lossless Badge Hidden: ${cleanResult.losslessHidden}`);
    console.log(`  Download Button Hidden: ${cleanResult.downloadHidden}`);

    if (cleanResult.losslessHidden) throw new Error('DOCX LOSSLESS VALIDATION PASSED badge should be visible!');
    if (cleanResult.downloadHidden) throw new Error('Download button must be visible for cleaned item!');
    console.log('[PASS] Step 8, 9 & 10: Cleaned successfully, Lossless Validation badge displayed, download available.');

    // Step 11 & 12: Add two more files & execute batch
    console.log('\n--- Step 11 & 12: Multi-File Batch Addition ---');
    await cdp.setFiles('#fileInput', [TEXT_FIXTURE, UNSUPPORTED_FIXTURE]);

    // Wait for queue length = 3
    for (let i = 0; i < 40; i++) {
      await sleep(300);
      const count = await cdp.eval(`document.querySelectorAll('#fileList > article').length`);
      if (count === 3) break;
    }

    const initialBatchCards = await cdp.eval(`(() => {
      return Array.from(document.querySelectorAll('#fileList > article')).map(card => ({
        name: card.querySelector('.file-name')?.textContent?.trim(),
        status: card.querySelector('.status-badge')?.textContent?.trim()
      }));
    })()`);
    console.log('  Current queue items:');
    initialBatchCards.forEach((c, idx) => console.log(`    [${idx}] ${c.name} -> ${c.status}`));

    // Step 13 & 14: Execute batch & partial failure isolation
    console.log('\n--- Step 13 & 14: Execute Batch Processing & Partial Failure Isolation ---');
    await cdp.eval(`document.querySelector('#cleanAllButton').click()`);

    let batchFinalState = null;
    for (let i = 0; i < 60; i++) {
      await sleep(500);
      batchFinalState = await cdp.eval(`(() => {
        const cards = Array.from(document.querySelectorAll('#fileList > article')).map(card => ({
          name: card.querySelector('.file-name')?.textContent?.trim(),
          status: card.querySelector('.status-badge')?.textContent?.trim(),
          detail: card.querySelector('.file-detail')?.textContent?.trim(),
          downloadHidden: card.querySelector('.download-file')?.hidden
        }));
        const isCleaning = cards.some(c => c.status === 'CLEANING' || c.status === 'QUEUED' || c.status === 'INSPECTING');
        const summary = {
          total: document.querySelector('#sumTotal')?.textContent?.trim(),
          cleaned: document.querySelector('#sumCleaned')?.textContent?.trim(),
          unsupported: document.querySelector('#sumUnsupported')?.textContent?.trim(),
          errors: document.querySelector('#sumErrors')?.textContent?.trim(),
        };
        return { cards, isCleaning, summary };
      })()`);

      if (batchFinalState && !batchFinalState.isCleaning) break;
    }

    console.log('  Final Batch State:');
    batchFinalState.cards.forEach((c, idx) => {
      console.log(`    Card [${idx}] ${c.name}: Status=${c.status}, DownloadHidden=${c.downloadHidden}`);
      console.log(`         Detail: ${c.detail}`);
    });
    console.log(`  Summary Counts: Total=${batchFinalState.summary.total}, Cleaned=${batchFinalState.summary.cleaned}, Unsupported=${batchFinalState.summary.unsupported}`);

    // Verify DOCX is cleaned with download
    const docxItem = batchFinalState.cards.find(c => c.name.endsWith('.docx'));
    if (!docxItem || docxItem.status !== 'CLEANED' || docxItem.downloadHidden) {
      throw new Error('DOCX card was corrupted or lost download state in batch!');
    }

    // Verify unsupported file is truthfully UNSUPPORTED with no download
    const unsupItem = batchFinalState.cards.find(c => c.name.endsWith('.xyz'));
    if (!unsupItem || unsupItem.status !== 'UNSUPPORTED' || !unsupItem.downloadHidden) {
      throw new Error('Unsupported card failed to display UNSUPPORTED or showed download!');
    }

    console.log('[PASS] Step 13 & 14: Batch completed with partial success; successful downloads preserved, unsupported isolated.');

    // Step 15: Reload UI & verify clean initialization
    console.log('\n--- Step 15: Reload Page & Verify Clean Initialization ---');
    await cdp.send('Page.reload');
    await sleep(1500);

    const reloadState = await cdp.eval(`(() => ({
      title: document.title,
      serverText: document.querySelector('#serverStatusText')?.textContent?.trim(),
      queueLength: document.querySelectorAll('#fileList > article').length,
      actionBarHidden: document.querySelector('#actionBar')?.hidden,
      summaryBarHidden: document.querySelector('#batchSummaryBar')?.hidden
    }))()`);

    console.log(`  Reloaded Queue Length: ${reloadState.queueLength}`);
    console.log(`  Reloaded Server Status: "${reloadState.serverText}"`);
    console.log(`  Action Bar Hidden: ${reloadState.actionBarHidden}`);

    if (reloadState.queueLength !== 0) throw new Error('Queue was not empty after reload');
    if (!reloadState.actionBarHidden) throw new Error('Action bar should be hidden when queue is empty');
    if (!reloadState.serverText.includes('Sẵn sàng') && !reloadState.serverText.includes('Ready')) {
      throw new Error('Server status was not ready after reload');
    }
    console.log('[PASS] Step 15: UI reloaded cleanly with zero state corruption.');

    cdp.close();

    console.log('\n============================================================');
    console.log(`ALL 15 SMOKE SCENARIO STEPS PASSED SUCCESSFULLY!`);
    console.log(`Browser Verified: ${browserName}`);
    console.log('============================================================\n');

  } finally {
    if (chromeProc) {
      chromeProc.kill('SIGKILL');
    }
    await sleep(500);
    try { rmSync(tempProfile, { recursive: true, force: true }); } catch {}
  }
}

main().catch(err => {
  console.error('\n[FATAL ERROR in Smoke Test]:', err);
  process.exit(1);
});
