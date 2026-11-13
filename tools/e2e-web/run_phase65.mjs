// React acceptance on loopback: UI fixtures, or real Docker/API with local data fixtures.
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve, extname } from "node:path";
import assert from "node:assert/strict";

const root = resolve(import.meta.dirname, "../..");
const output = mkdtempSync(`${tmpdir()}/namira-phase65-`);
const phase7 = process.argv.includes("--phase7");
const realDocker = phase7 || process.argv.includes("--real-docker");
const reviewRun = process.argv.includes('--review-run') ? process.argv[process.argv.indexOf('--review-run') + 1] : null;
const demoRun = process.argv.includes('--demo-run') ? process.argv[process.argv.indexOf('--demo-run') + 1] : null;
let backendProcess, apiOrigin, realCases;
if (reviewRun || demoRun) apiOrigin = 'http://127.0.0.1:8765'; // Read-only review; never starts a campaign.
async function startBackend(reuse = false) {
  const proc = spawn(process.env.PYTHON || `${root}/.venv/bin/python`, ["-u",
    `${root}/tools/e2e-web/phase65_fixture_server.py`, "--directory", `${output}/backend`, ...(reuse ? ["--reuse"] : []), ...(phase7 ? ['--phase7'] : [])],
    {stdio: ["ignore", "pipe", "pipe"]});
  backendProcess = proc;
  const ready = await new Promise((ok, fail) => {
    let text = "", errors = "";
    const timer = setTimeout(() => { proc.kill(); fail(new Error(`Backend startup timeout: ${errors}`)); }, 55000);
    proc.stderr.on("data", b => { errors += b; });
    proc.stdout.on("data", b => {
      text += b;
      for (const line of text.split("\n")) if (line.startsWith('{"url":')) {
        clearTimeout(timer); ok(JSON.parse(line)); return;
      }
    });
    proc.on("error", e => { clearTimeout(timer); fail(e); });
    proc.on("exit", code => { clearTimeout(timer); if (code) fail(new Error(`Backend exited ${code}: ${errors}`)); });
  });
  apiOrigin = ready.url; realCases = ready.cases;
}
async function stopBackend() {
  if (!backendProcess || backendProcess.exitCode !== null) return;
  const proc = backendProcess; proc.kill("SIGTERM");
  await new Promise(r => proc.once("exit", r));
  backendProcess = null;
}
if (realDocker) await startBackend();
const result = {run_id: "fixture", target: "https://fixture.invalid/", status: "completed",
  started_at: "2026-11-13T00:00:00Z", ended_at: "2026-11-13T00:00:02Z",
  actions: [], observations: [], findings: [], recommendations: [], summary: {requests: 0}};
const hypotheses = [{hypothesis_id: "h1", vulnerability_id: "CVE-FIXTURE-1", technology: "Fixture",
  version: "1.0.0", correlation_status: "candidate", source_refs: ["fixture"], evidence_refs: ["e1"],
  applicability_conditions: ["Aplicabilidade no alvo não validada."], limitations: ["Dados locais de teste."]},
  {hypothesis_id: "h2", vulnerability_id: "CVE-FIXTURE-2", technology: "Fixture", correlation_status: "version_unknown"}];
const executions = ["planned", "running", "completed", "failed", "cancelled", "inconclusive", "skipped"].map((status, i) => ({
  campaign_id: "fixture", task_id: `task-${i}`, execution_id: `execution-${i}`, agent_id: "laboratory_validation",
  operation_id: i === 2 ? "correlate_local_version" : "compare_local_results", execution_backend: i === 3 ? "docker" : "simulated",
  execution_status: status, validation_status: "inconclusive", hypothesis_id: i === 2 ? "h1" : null,
  worker_id: i ? `fixture-worker-${i}` : null, evidence_refs: i === 2 ? ["e1"] : [],
  started_at: i ? "2026-11-13T00:00:00Z" : null, finished_at: i > 1 ? "2026-11-13T00:00:02Z" : null,
  duration_ms: i > 1 ? 2000 : null, result_summary: "Registro de fixture local.",
  selection_reason: "Verificação determinística registrada para a fixture.", limitations: ["Não confirma vulnerabilidade no alvo."]}));
const evidence_catalog = [{evidence_id: "e1", title: "Inventário de framework", source: "fixture",
  technology: "Fixture", version: "1.0.0", certainty: "exact", summary: "Metadados locais sem conteúdo bruto."}];
const payload = {result, executions, hypotheses, evidence_catalog};
const server = createServer(async (req, res) => {
  if (req.method !== "GET") { res.writeHead(405).end(); return; }
  const path = new URL(req.url, "http://localhost").pathname;
  if (path.startsWith("/api/")) {
    res.setHeader("Content-Type", "application/json");
    if (realDocker || reviewRun || demoRun) {
      try {
        const response = await fetch(`${apiOrigin}${req.url}`);
        res.writeHead(response.status).end(await response.text());
      } catch { res.writeHead(502).end(JSON.stringify({error: "Real fixture backend unavailable"})); }
      return;
    }
    if (path === "/api/status") res.end(JSON.stringify({...payload, running: false, events: [], approvals: [], scope: {target: result.target}, report_available: true}));
    else if (path === "/api/history/fixture") res.end(JSON.stringify(payload));
    else if (path === "/api/history") res.end(JSON.stringify({runs: [{...result, findings_count: 0}], warnings: []}));
    else res.writeHead(404).end("{}");
    return;
  }
  const filename = resolve(root, "frontend/dist", path === "/" ? "index.html" : `.${path}`);
  if (!filename.startsWith(`${root}/frontend/dist/`)) { res.writeHead(403).end(); return; }
  try {
    res.setHeader("Content-Type", ({".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".woff2": "font/woff2"})[extname(filename)] || "application/octet-stream");
    res.end(readFileSync(filename));
  } catch { res.writeHead(404).end(); }
});
await new Promise(r => server.listen(0, "127.0.0.1", r));
const origin = `http://127.0.0.1:${server.address().port}`;
const chrome = spawn(process.env.CHROME_BIN || "google-chrome", ["--headless=new", "--disable-gpu",
  "--disable-background-networking", "--no-first-run", "--no-default-browser-check", "--remote-debugging-port=0",
  `--user-data-dir=${output}/profile`, "--window-size=1440,1000", "about:blank"], {stdio: ["ignore", "ignore", "pipe"]});
let ws;
try {
  const port = await new Promise((ok, fail) => {
    let log = "";
    const timer = setTimeout(() => fail(new Error(`Chrome startup timeout: ${log.slice(-500)}`)), 15000);
    chrome.stderr.on("data", data => { log += data; const match = log.match(/DevTools listening on (ws:\/\/\S+)/);
      if (match) { clearTimeout(timer); ok(new URL(match[1]).port); } });
    chrome.on("error", error => { clearTimeout(timer); fail(error); });
    chrome.on("exit", code => { clearTimeout(timer); fail(new Error(`Chrome exited ${code}: ${log.slice(-500)}`)); });
  });
  const page = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find(t => t.type === "page");
  ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((ok, fail) => { ws.onopen = ok; ws.onerror = fail; });
  let seq = 0;
  const pending = new Map(), errors = [];
  const send = (method, params = {}) => new Promise((ok, fail) => {
    const id = ++seq; pending.set(id, {ok, fail}); ws.send(JSON.stringify({id, method, params}));
  });
  ws.onmessage = ({data}) => {
    const m = JSON.parse(data);
    if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.fail(new Error(JSON.stringify(m.error))) : p.ok(m.result); }
    if (m.method === "Runtime.exceptionThrown") errors.push(m.params.exceptionDetails.text);
    if (m.method === "Fetch.requestPaused") {
      const local = m.params.request.url.startsWith(`${origin}/`);
      send(local ? "Fetch.continueRequest" : "Fetch.failRequest", {requestId: m.params.requestId, ...(local ? {} : {errorReason: "BlockedByClient"})})
        .catch(error => { // Navigation can cancel an already paused request.
          if (!error.message.includes('Invalid InterceptionId')) errors.push(error.message);
        });
    }
  };
  await send("Runtime.enable"); await send("Page.enable"); await send("Fetch.enable", {patterns: [{urlPattern: "*"}]});
  const evaluate = async expression => {
    const r = await send("Runtime.evaluate", {expression, returnByValue: true});
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };
  const waitFor = async expression => {
    for (let i = 0; i < 50; i++) {
      if (await evaluate(`Boolean(${expression})`)) return;
      await new Promise(r => setTimeout(r, 100));
    }
    throw new Error(`UI condition not met: ${expression}`);
  };
  const shot = async name => {
    await evaluate("document.getAnimations().filter(a => a.effect.getTiming().iterations !== Infinity).forEach(a => a.finish())");
    writeFileSync(`${output}/${name}.png`, Buffer.from((await send("Page.captureScreenshot", {format: "png"})).data, "base64"));
  };
  const reveal = async selector => evaluate(`(() => {
    const element = document.querySelector(${JSON.stringify(selector)});
    const parents = []; for (let p = element; p; p = p.parentElement) if (p.tagName === 'DETAILS') parents.push(p);
    for (const p of parents.reverse()) if (!p.open) p.querySelector(':scope > summary').click();
  })()`);
  const passed = [];
  if (demoRun) {
    const data = await (await fetch(`${origin}/api/history/${encodeURIComponent(demoRun)}`)).json();
    assert.equal(data.result.demo.demo_id, 'namira-auditable-v1');
    assert.equal(data.result.execution_status, 'completed');
    assert.equal(data.result.assessment_status, 'partial');
    passed.push('real saved API separates execution completion and partial assessment');
    const docker = data.executions.filter(e => e.worker_id && e.execution_backend === 'docker');
    assert.equal(docker.length, 4);
    for (const e of docker) {
      assert.equal(e.worker_responded, true); assert.equal(e.cleanup_status, 'completed');
      assert.equal(e.terminal_capture.execution_id, e.execution_id); assert.equal(e.terminal_capture.exit_code, 0);
      assert.equal(e.terminal_capture.capture_available, true);
    }
    passed.push('four Docker executions linked to actual process capture and cleanup');
    assert.equal(data.verification_summary.target_requests, 0);
    assert.equal(data.verification_summary.target_responses, 0);
    passed.push('fixture reads are not presented as live target responses');
    const diagnostic = docker.find(e => e.operation_id === 'inspect_demo_environment');
    const captured = JSON.parse(diagnostic.terminal_capture.stdout_excerpt);
    assert.equal(captured.task_id, diagnostic.execution_id);
    assert.equal(captured.output.commands.length, 4);
    assert.match(captured.output.commands[1].stdout, /uid=65534/);
    assert.match(captured.output.commands[2].stdout, /Linux/);
    passed.push('real runtime, non-root identity, system and fixture hash captured');
    assert.deepEqual(docker.filter(e => e.hypothesis_id).map(e => e.validation_status).sort(), ['contradicted','inconclusive','supported']);
    passed.push('three distinct comparison outcomes');
    assert.ok(data.conclusions.some(c => c.initial_status === 'suspected' && c.current_status === 'rejected' && c.revisions.some(r => r.revision.accepted)));
    passed.push('independent revision preserves original suspected conclusion');
    const denied = data.executions.find(e => e.task_id === 'demo_policy_control');
    assert.equal(denied.authorization_status, 'denied'); assert.equal(denied.worker_id, null);
    passed.push('unknown operation rejected with no worker');
    await send('Page.navigate', {url: `${origin}/#test/${encodeURIComponent(demoRun)}`});
    await waitFor("document.querySelector('.execution-history')");
    await evaluate("[...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Pular')?.click()");
    assert.match(await evaluate("document.querySelector('.assessment-summary').innerText"), /Parcial/);
    assert.match(await evaluate("document.querySelector('.assessment-summary').innerText"), /DEMONSTRAÇÃO/);
    passed.push('demo provenance and partial completeness visible');
    await reveal('.execution-history');
    assert.equal(await evaluate("document.querySelectorAll('.terminal-capture').length"), 4);
    assert.equal(await evaluate("document.querySelectorAll('.terminal-capture[open]').length"), 0);
    passed.push('terminal is read-only and collapsed by default');
    await reveal(`[data-execution-id="${diagnostic.execution_id}"] .terminal-capture`);
    const terminalText = await evaluate(`document.querySelector('[data-execution-id="${diagnostic.execution_id}"] .terminal-capture').innerText`);
    assert.match(terminalText, /uid=65534/); assert.match(terminalText, /stdout/); assert.match(terminalText, /stderr/);
    passed.push('React shows actual separate process streams');
    await evaluate("document.querySelector('.pipeline-position-7').click()");
    assert.match(await evaluate("document.querySelector('.xai-detail').innerText"), /Parcial/);
    assert.equal(await evaluate("document.querySelectorAll('.pipeline-card').length"), 8);
    passed.push('eight pipeline cards and saved XAI preserve assessment');
    const report = await (await fetch(`${origin}/api/history/${demoRun}/report.md`)).text();
    assert.match(report, /Relatório de Demonstração Auditável/); assert.match(report, /partial/);
    assert.match(report, /suspected → rejected/);
    passed.push('saved report matches classification history');
    await shot('demo-terminal');
    await send('Page.reload');
    await waitFor(`document.querySelector('[data-execution-id="${diagnostic.execution_id}"]')`);
    assert.equal(await evaluate("document.querySelectorAll('.terminal-capture').length"), 4);
    passed.push('reload preserves execution identities and captured output');
    await send('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
    await reveal(`[data-execution-id="${diagnostic.execution_id}"] .terminal-capture`);
    assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true);
    passed.push('mobile capture has no page overflow');
    assert.deepEqual(errors, []); passed.push('no browser exceptions');
  } else if (reviewRun) {
    const data = await (await fetch(`${origin}/api/history/${encodeURIComponent(reviewRun)}`)).json();
    const summary = data.verification_summary;
    assert.equal(summary.kali_execution, 'not_recorded');
    await send('Page.navigate', {url: `${origin}/#test/${encodeURIComponent(reviewRun)}`});
    await waitFor("document.querySelector('.execution-history')");
    await reveal('.execution-history');
    const overview = await evaluate("document.querySelector('.verification-overview').innerText");
    assert.ok(overview.includes(`${summary.target_responses}\nrespostas HTTP`));
    assert.ok(overview.includes(`${summary.local_checks_completed}\ncomparações locais`));
    assert.ok(overview.includes(`${summary.hypotheses_compared} de ${summary.hypotheses_total}`));
    assert.ok(overview.includes('execução no Kali'));
    passed.push('HTTP responses, local comparisons and Kali execution are distinct');
    assert.equal(await evaluate("[...document.querySelectorAll('.workflow-group')].every(e=>!e.open)"), true);
    passed.push('internal stages collapsed by default');
    const row = data.executions.find(e => e.presentation.outcome === 'O aviso descreve outro produto');
    assert.ok(row, 'This regression scenario requires a historical cross-product comparison');
    const selector = `[data-execution-id="${row.execution_id}"]`;
    await reveal(selector);
    let text = await evaluate(`document.querySelector(${JSON.stringify(selector)}).innerText`);
    assert.ok(text.includes(row.presentation.explanation));
    assert.ok(text.includes('Esta operação não é um teste no Kali.'));
    assert.ok(!text.includes(row.worker_id));
    assert.equal(await evaluate(`document.querySelector(${JSON.stringify(selector + ' .execution-audit')}).open`), false);
    passed.push('product mismatch explained without raw IDs or misleading execution claim');
    await evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView()`);
    await shot('report-readable-desktop');
    await reveal(selector + ' .execution-audit');
    text = await evaluate(`document.querySelector(${JSON.stringify(selector)}).innerText`);
    assert.ok(text.includes(row.worker_id));
    assert.ok(text.includes(row.result_summary));
    passed.push('original audit remains accessible');
    await evaluate(`document.querySelector(${JSON.stringify(selector + ' .review-link')}).click()`);
    await waitFor("document.querySelector('.hypothesis-card[open]')");
    assert.ok((await evaluate("document.querySelector('.hypothesis-card[open]').innerText")).includes(row.presentation.outcome));
    assert.equal(await evaluate("document.querySelector('.hypothesis-card[open] .conclusion-history').open"), false);
    passed.push('hypothesis navigation retains result and collapsed revision history');
    await send('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
    assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true);
    await shot('report-readable-mobile');
    passed.push('saved report fits mobile viewport');
    assert.deepEqual(errors, []);
    passed.push('no browser exceptions');
  } else if (realDocker) {
    const listing = await (await fetch(`${origin}/api/history`)).json();
    assert.deepEqual(listing.warnings, []);
    assert.ok(realCases.every(c => listing.runs.some(r => r.run_id === c.run_id)));
    passed.push("real API lists all fixture campaigns without internal-directory warnings");
    const originals = {};
    for (const test of realCases) {
      const data = await (await fetch(`${origin}/api/history/${test.run_id}`)).json();
      originals[test.scenario] = data;
      writeFileSync(`${output}/api-${test.scenario}.json`, JSON.stringify(data, null, 2));
      const row = data.executions.find(e => e.execution_id === test.execution_id);
      assert.equal(data.hypotheses[0].hypothesis_id, test.hypothesis_id);
      await send("Page.navigate", {url: `${origin}/#test/${test.run_id}`});
      await waitFor(`document.querySelector('.execution-history[data-campaign-id="${test.run_id}"]')`);
      await evaluate("(()=>{const summary=[...document.querySelectorAll('summary')].find(e=>e.textContent.includes('Verificações e hipóteses desta campanha')); if (!summary.parentElement.open) summary.click()})()");
      await evaluate("document.querySelector('.execution-tabs button').click()");
      if (test.scenario === "unverified") {
        assert.equal(row, undefined);
        await evaluate("document.querySelectorAll('.execution-tabs button')[1].click()");
        await waitFor("document.querySelector('.hypothesis-card')");
        await evaluate("document.querySelector('.hypothesis-card > summary').click()");
        assert.match(await evaluate("document.querySelector('.hypothesis-card').innerText"), /Sem comparação local registrada/);
      } else {
        assert.equal(row.execution_backend, "docker");
        assert.equal(row.worker_responded, true);
        assert.equal(row.authorization_status, "approved");
        assert.equal(row.hypothesis_id, test.hypothesis_id);
        assert.equal(row.validation_status, test.scenario === "failed" ? "not_evaluated" : test.scenario);
        const recorded = data.result.observations.find(o => o.execution_id === row.execution_id);
        assert.equal(recorded.worker_id, row.worker_id);
        assert.equal(recorded.task_id, row.task_id);
        assert.equal(recorded.validation_status, row.validation_status);
        const events = data.result.execution_events;
        assert.ok(events.some(e => e.task_id === row.task_id && e.event_type === "task_planned"));
        const authorized = events.findIndex(e => e.execution_id === row.execution_id && e.authorization_status === "approved");
        const dispatched = events.findIndex(e => e.execution_id === row.execution_id && e.event_type === "validation_started");
        assert.ok(authorized >= 0 && dispatched > authorized);
        assert.ok(!JSON.stringify(data.result.findings).includes("CVE-2099-6501"));
        const selector = `[data-execution-id="${test.execution_id}"]`;
        await waitFor(`document.querySelector(${JSON.stringify(selector)})`);
        await reveal(selector);
        const body = await evaluate(`document.querySelector(${JSON.stringify(selector)}).innerText`);
        assert.match(body, /Docker/);
        assert.ok(body.includes("Esta operação não é um teste no Kali."));
        assert.ok(!body.includes(row.worker_id), "worker ID must be collapsed by default");
        assert.equal(await evaluate(`document.querySelector(${JSON.stringify(selector + ' .execution-audit')}).open`), false);
        const expected = row.presentation.outcome;
        assert.ok(body.includes(expected), body);
        await reveal(selector + ' .execution-audit');
        const audit = await evaluate(`document.querySelector(${JSON.stringify(selector)}).innerText`);
        assert.ok(audit.includes(row.worker_id));
        assert.ok(audit.includes(row.task_id));
        assert.ok(audit.includes(row.result_summary));
        if (test.scenario === "failed") {
          assert.deepEqual(row.output_evidence_refs, []);
          assert.equal(row.execution_status, "failed");
        } else {
          const evidence = data.evidence_catalog.find(e => e.evidence_id === row.output_evidence_refs[0]);
          assert.equal(evidence.execution_id, row.execution_id);
          assert.equal(evidence.worker_id, row.worker_id);
          assert.equal(evidence.validation_status, test.scenario);
          assert.ok(evidence.criteria.length);
          await reveal(selector + ' .evidence-section');
          await evaluate(`Array.from(document.querySelectorAll(${JSON.stringify(selector + ' .execution-evidence > details > summary')})).find(e=>e.textContent==='Resultado da verificação local').click()`);
          assert.ok(!(await evaluate(`document.querySelector(${JSON.stringify(selector)}).innerText`)).includes(evidence.sha256));
          await reveal(selector + ' .execution-evidence > details[open] .technical-record');
          const details = await evaluate(`document.querySelector(${JSON.stringify(selector)}).innerText`);
          assert.ok(details.includes(evidence.sha256));
          assert.ok(details.includes("fixture-local"));
          if (test.scenario === "supported") {
            await evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView()`);
            await shot("real-docker-supported");
          }
        }
        await evaluate("document.querySelectorAll('.execution-tabs button')[1].click()");
        await waitFor("document.querySelector('.hypothesis-card')");
        await evaluate("document.querySelector('.hypothesis-card > summary').click()");
        assert.ok((await evaluate("document.querySelector('.hypothesis-card').innerText")).includes(expected));
      }
      if (phase7) {
        const conclusion = data.conclusions.find(c => c.subject_id === test.hypothesis_id);
        const revision = conclusion.revisions[0].revision;
        assert.equal(revision.revision_id, test.revision_id);
        assert.equal(conclusion.current_status, test.current_status);
        assert.equal(data.result.conclusions.find(c => c.subject_id === test.hypothesis_id).current_status, test.current_status);
        const revisionSelector = `[data-revision-id="${test.revision_id}"]`;
        await waitFor(`document.querySelector(${JSON.stringify(revisionSelector)})`);
        await reveal(revisionSelector + ' .technical-record');
        const text = await evaluate(`document.querySelector(${JSON.stringify(revisionSelector)}).innerText`);
        assert.ok(text.includes(revision.reason));
        assert.ok(text.includes(conclusion.reflection.reasoning_summary));
        assert.ok(text.includes(revision.evidence_fingerprint));
        if (test.scenario === 'contradicted') {
          assert.equal(conclusion.initial_status, 'potential');
          assert.equal(revision.approved_status, 'rejected');
          assert.ok(conclusion.validation.contradicting_evidence_refs.length);
          assert.ok(text.includes('Proposta aprovada'));
          await evaluate(`document.querySelector(${JSON.stringify(revisionSelector)}).scrollIntoView()`);
          await shot('phase7-contradiction-revised');
          await evaluate("document.querySelector('.execution-tabs button').click()");
          await reveal(`[data-execution-id="${test.execution_id}"]`);
          await evaluate(`document.querySelector('[data-execution-id="${test.execution_id}"] .review-link').click()`);
          assert.equal(await evaluate(`document.querySelector('[data-hypothesis-id="${test.hypothesis_id}"]').open`), true);
        }
        if (test.scenario === 'inconclusive') {
          assert.equal(revision.proposed_status, 'confirmed');
          assert.equal(revision.accepted, false);
          assert.ok(text.includes('Proposta rejeitada'));
          await evaluate(`document.querySelector(${JSON.stringify(revisionSelector)}).scrollIntoView()`);
          await shot('phase7-unjustified-ai-rejected');
        }
        passed.push(`persisted reflection and decision visible: ${test.scenario}`);
      }
      passed.push(`real Docker/API/React: ${test.scenario}`);
    }
    await stopBackend(); await startBackend(true);
    for (const test of realCases) {
      const after = await (await fetch(`${origin}/api/history/${test.run_id}`)).json();
      assert.deepEqual(after, originals[test.scenario]);
    }
    passed.push("server restart preserves executions, criteria, hypotheses and evidence");
    const supported = realCases.find(c => c.scenario === "supported");
    await send("Page.navigate", {url: `${origin}/#test/${supported.run_id}`});
    await waitFor(`document.querySelector('.execution-history[data-campaign-id="${supported.run_id}"]')`);
    await send("Page.reload");
    await waitFor(`document.querySelector('.execution-history[data-campaign-id="${supported.run_id}"]')`);
    await evaluate("[...document.querySelectorAll('summary')].find(e=>e.textContent.includes('Verificações e hipóteses desta campanha')).click()");
    await waitFor(`document.querySelector('[data-execution-id="${supported.execution_id}"]')`);
    passed.push("page reload shows the same real execution");
    if (phase7) {
      await evaluate("document.querySelectorAll('.execution-tabs button')[1].click()");
      await waitFor(`document.querySelector('[data-revision-id="${supported.revision_id}"]')`);
      passed.push('page reload retains classification revision after server restart');
    }
    await send("Emulation.setDeviceMetricsOverride", {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
    assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true);
    passed.push("real history mobile layout without overflow");
    await evaluate("location.hash='research'");
    await waitFor("document.querySelectorAll('.pipeline-card').length === 8");
    passed.push("eight pipeline cards preserved");
    if (phase7) {
      await waitFor("document.querySelector('.xai-revisions')");
      await evaluate("document.querySelector('.xai-revisions > summary').click()");
      const live = await (await fetch(`${origin}/api/status`)).json();
      assert.equal(live.observability.mode, 'v2');
      const persisted = live.conclusions[0].revisions[0];
      const selector = `.xai-revisions [data-revision-id="${persisted.revision.revision_id}"]`;
      await reveal(selector);
      assert.ok((await evaluate("document.querySelector('.xai-revisions').innerText")).includes(persisted.revision.reason));
      passed.push('XAI exposes persisted validation/reflection/decision after restart');
    }
    assert.deepEqual(errors, []); passed.push("no browser exceptions");
  } else {
  await send("Page.navigate", {url: `${origin}/#executions`});
  await waitFor("document.querySelectorAll('.execution-card').length === 7"); passed.push("7 distinct execution states");
  await evaluate("document.querySelector('[data-status=completed] > summary').click()");
  assert.match(await evaluate("document.querySelector('[data-status=completed]').innerText"), /não significa que uma vulnerabilidade foi reproduzida/); passed.push("completion does not claim reproduction");
  assert.equal(await evaluate("document.querySelector('[data-status=completed] .execution-audit').open"), false);
  await reveal('[data-status=completed] .execution-evidence > details');
  assert.match(await evaluate("document.querySelector('[data-status=completed]').innerText"), /Metadados locais/); passed.push("evidence metadata visible");
  await shot("executions-desktop");
  await evaluate("document.querySelector('select').value='failed'; document.querySelector('select').dispatchEvent(new Event('change', {bubbles:true}))");
  await waitFor("document.querySelectorAll('.execution-card').length === 1");
  assert.match(await evaluate("document.querySelector('.execution-card').innerText"), /Falhou/); passed.push("failure filter");
  await evaluate("document.querySelectorAll('.execution-tabs button')[1].click()");
  await waitFor("document.querySelectorAll('.hypothesis-card').length === 2");
  await evaluate("document.querySelectorAll('.hypothesis-card > summary')[1].click()");
  assert.match(await evaluate("document.querySelectorAll('.hypothesis-card')[1].innerText"), /Sem comparação local registrada/); passed.push("unverified hypothesis not confirmed");
  await send("Emulation.setDeviceMetricsOverride", {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
  assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true); passed.push("mobile layout without overflow");
  await shot("hypotheses-mobile");
  await send("Page.reload"); await waitFor("document.querySelectorAll('.execution-card').length === 7"); passed.push("reload retains backend records");
  await evaluate("location.hash='test/fixture'");
  await waitFor("[...document.querySelectorAll('summary')].some(e => e.textContent.includes('Verificações e hipóteses desta campanha'))");
  await evaluate("[...document.querySelectorAll('summary')].find(e=>e.textContent.includes('Verificações e hipóteses desta campanha')).click()");
  await waitFor("document.querySelectorAll('.execution-card').length === 7"); passed.push("saved campaign history");
  await evaluate("location.hash='research'");
  await waitFor("document.querySelectorAll('.pipeline-card').length === 8"); passed.push("eight pipeline cards preserved");
  assert.deepEqual(errors, []); passed.push("no browser exceptions");
  }
  const report = {mode: demoRun ? 'auditable-demo-real-docker-readonly' : reviewRun ? 'saved-report-readonly' : phase7 ? "phase7-real-docker-and-api" : realDocker ? "real-docker-and-api" : "ui-fixtures", passed: passed.length, checks: passed, artifacts: output};
  writeFileSync(`${output}/acceptance.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} finally {
  ws?.close(); chrome.kill("SIGTERM");
  await new Promise(r => chrome.exitCode !== null ? r() : chrome.once("exit", r));
  server.closeAllConnections(); await new Promise(r => server.close(r));
  await stopBackend();
  rmSync(`${output}/profile`, {recursive: true, force: true, maxRetries: 5, retryDelay: 100});
}
