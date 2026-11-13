import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { createRoot } from "react-dom/client";
import {
  Activity, ArrowDownToLine, ArrowLeft, ArrowRight, ArrowUpRight,
  CircleHelp, Eye, EyeOff, FileText, LoaderCircle, ScanLine,
  Settings as SettingsIcon, ShieldAlert, X,
} from "lucide-react";
import AgentPipeline from "./components/ui/ai-agent-pipeline";
import XaiPanel from "./components/ui/xai-panel";
import ExecutionHistory from "./components/ui/execution-history";
import ConclusionReview from "./components/ui/conclusion-review";
import AssessmentStatus, { assessmentLabel } from "./components/ui/assessment-status";
import "./styles.css";

const STATUS_LABELS = {
  idle: "Pronto para pesquisar",
  running: "Pesquisando",
  stopping: "Parada solicitada",
  completed: "Pesquisa concluída",
  inconclusive: "Pesquisa inconclusiva",
  stopped: "Pesquisa interrompida",
  failed: "Pesquisa com erro",
};

const PHASE_LABELS = {
  scope: "Escopo",
  discovery: "Descoberta",
  planning: "Planejamento",
  checks: "Verificações",
  surface_checks: "Superfície pública",
  triage: "Triagem",
  remediation: "Recomendações",
  target_analysis: "Análise complementar",
  ai: "Análise por IA",
  approval: "Aprovação",
  complete: "Conclusão",
  monitor: "Comparação",
};

const CHECK_LABELS = {
  missing_hsts: "Política HSTS",
  missing_nosniff: "Proteção MIME",
  missing_referrer_policy: "Política de referência",
  missing_csp: "Content Security Policy",
  missing_frame_protection: "Proteção contra incorporação",
  cookie_flags: "Atributos de cookies",
  ftp_listing: "Índice de diretório público",
  public_metrics: "Endpoint de métricas",
  sql_error_exposure: "Tratamento de erros da busca",
  source_map_reference: "Referência de source map",
};

const INSIGHT_TYPES = new Set([
  "test",
  "observation",
  "triage",
  "agent_start",
  "agent_result",
  "agent_error",
  "decision",
  "evidence_link",
  "request",
  "response",
  "error",
  "denied",
  "control",
  "campaign",
  "stop",
]);

const PAGES = [
  ["home", "Início", "01"],
  ["research", "Acompanhamento", "02"],
  ["findings", "Achados", "03"],
  ["executions", "Verificações e hipóteses", ""],
  ["reports", "Relatórios", "04"],
  ["settings", "Configuração do projeto", "05"],
  ["test", "Teste salvo", ""],
];

const PAGE_ICONS = { home: ScanLine, research: Activity, findings: ShieldAlert, reports: FileText, settings: SettingsIcon };

const SEVERITY_LABELS = { critical: "Crítica", high: "Alta", medium: "Média", low: "Baixa", info: "Informativa" };
const FINDING_STATES = { confirmed: "Observação confirmada", inconclusive: "Inconclusivo", discarded: "Descartado" };

function currentPage() {
  const page = window.location.hash.slice(1);
  if (/^test\/[A-Za-z0-9][A-Za-z0-9_-]{0,95}$/.test(page)) return "test";
  if (page === "scope") return "settings";
  return PAGES.some(([id]) => id !== "test" && id === page) ? page : "home";
}

function formatDate(value) {
  const date = new Date(value);
  return value && !Number.isNaN(date.getTime())
    ? date.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })
    : "Data não registrada";
}

async function getJson(path, signal) {
  const response = await fetch(path, { cache: "no-store", signal });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Falha HTTP ${response.status}.`);
  return data;
}

function SettingsModal({ children, onClose, pendingScan = false }) {
  const dialog = useRef(null);
  useEffect(() => {
    const element = dialog.current;
    const previousFocus = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    element.showModal();
    return () => {
      element.close();
      document.body.style.overflow = previousOverflow;
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
    };
  }, []);
  return (
    <dialog ref={dialog} className="settings-modal" aria-labelledby="modal-title"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          onClose();
        }
      }}
      onClose={(event) => { if (!event.currentTarget.open) onClose(); }} onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}>
      <div className="modal-content">
        <header className="modal-heading">
          <div><p className="eyebrow">Próxima pesquisa</p><h2 id="modal-title">Configurações de IA</h2></div>
          <button type="button" className="modal-close" aria-label="Fechar configurações" onClick={onClose}><X size={20} aria-hidden="true" /></button>
        </header>
        {children}
        <button type="button" className="settings-done" onClick={onClose}>
          {pendingScan ? "Salvar e iniciar varredura" : "Concluir configurações"}
        </button>
      </div>
    </dialog>
  );
}

function ConsoleLayout({ view, state, assessment, connected, onNewSearch, children }) {
  return (
    <div className={`console-layout ${view === "home" ? "focused-home" : ""}`}>
      <a className="skip-link" href="#page-content" onClick={(event) => {
        event.preventDefault();
        document.getElementById("page-content")?.focus();
      }}>Pular para o conteúdo</a>
      <aside className="sidebar">
        <a className="brand brand-logo" href="#home" aria-label="NA MIRA, página inicial">
          <img className="brand-logo-img" src="/images/logo-horizontal.png" alt="NA MIRA" />
        </a>
        <p className="nav-label">Área de trabalho</p>
        <nav className="main-nav" aria-label="Navegação principal">
          {PAGES.filter(([id]) => !["home", "test"].includes(id)).map(([id, label]) => {
            const Icon = PAGE_ICONS[id] || Activity;
            return (
            <a key={id} href={`#${id}`} aria-current={view === id ? "page" : undefined}>
              <span aria-hidden="true"><Icon size={16} /></span>{label}
            </a>
            );
          })}
        </nav>
        <div className="sidebar-note">
          <strong>Pesquisa com limites.</strong>
          <p>Somente alvos autorizados. Evidências antes de conclusões.</p>
        </div>
      </aside>
      <div className="workspace">
        {view !== "home" && <header className="workspace-header">
          <span className={`status-pill status-${connected ? state : "failed"}`}>
            <span className="status-dot" />
            {connected ? (state === "completed" && assessment && assessment !== "complete"
              ? `Execução encerrada · análise ${assessmentLabel(assessment).toLowerCase()}` : STATUS_LABELS[state] || state) : "API desconectada"}
          </span>
          <div className="workspace-header-actions">
            <a className="header-new-scan" href="#home" onClick={(event) => {
              event.preventDefault();
              onNewSearch();
            }}>
              <ScanLine size={16} aria-hidden="true" />
              Nova varredura
            </a>
          </div>
        </header>}
        <div id="page-content" className="page-transition" key={view} tabIndex={-1}>{children}</div>
      </div>
    </div>
  );
}

function AISettings({ provider, onProviderChange, model, setModel, apiKey, setApiKey, region, setRegion, disabled }) {
  const [keyVisible, setKeyVisible] = useState(false);

  useEffect(() => {
    setKeyVisible(false);
  }, [provider, apiKey === ""]);

  return (
    <fieldset className="ai-fields" disabled={disabled}>
      <legend>Orientação por inteligência artificial</legend>
      <label className="setting-field" htmlFor="ai-provider">
        Provedor
        <select id="ai-provider" value={provider} onChange={(event) => onProviderChange(event.target.value)}>
          <option value="openai">OpenAI</option>
          <option value="bedrock">AWS Bedrock</option>
        </select>
      </label>
      <label className="setting-field" htmlFor="ai-model">
        Modelo
        <input id="ai-model" value={model} onChange={(event) => setModel(event.target.value)}
          list={`models-${provider}`} placeholder={provider === "bedrock" ? "Model ID, inference profile ID ou ARN" : "ID do modelo OpenAI"}
          autoComplete="off" />
        <datalist id={`models-${provider}`}>
          {provider === "bedrock" ? <option value="amazon.nova-micro-v1:0" /> : <option value="gpt-6-luna" />}
        </datalist>
      </label>
      {provider === "bedrock" && (
        <>
          <label className="setting-field" htmlFor="aws-region">
            Região AWS
            <input id="aws-region" value={region} onChange={(event) => setRegion(event.target.value)}
              placeholder="Padrão do servidor (ex.: us-east-1)" autoComplete="off" />
          </label>
          <p className="settings-note">Requer o extra Python bedrock, permissão bedrock:InvokeModel e acesso ao modelo na região escolhida.</p>
        </>
      )}
        <div className="credential-field">
          <label className="setting-field" htmlFor="api-key">
            Chave do modelo <small>{provider === "bedrock" ? "API key Amazon Bedrock" : "API key OpenAI"}</small>
          </label>
          <p id="api-key-help">{provider === "bedrock"
            ? "Cole sua API key do Amazon Bedrock (bearer token). Não use AWS Access Key ID ou Secret Access Key. Deixe em branco para usar o token ou as credenciais AWS configurados no servidor."
            : "Cole a chave para autenticar esta pesquisa. Deixe em branco se já estiver configurada no servidor."}</p>
          <div className="key-input">
            <input id="api-key" type={keyVisible ? "text" : "password"} value={apiKey} onChange={(event) => setApiKey(event.target.value)}
              placeholder={provider === "bedrock" ? "Cole sua API key do Bedrock aqui" : "Cole sua chave de API aqui"} autoComplete="off" spellCheck={false} aria-describedby="api-key-help" />
            <button type="button" onClick={() => setKeyVisible((visible) => !visible)}
              aria-controls="api-key" aria-pressed={keyVisible}
              aria-label={keyVisible ? "Ocultar chave do modelo" : "Mostrar chave do modelo"}>
              {keyVisible ? <EyeOff size={16} aria-hidden="true" /> : <Eye size={16} aria-hidden="true" />}
              {keyVisible ? "Ocultar" : "Mostrar"}
            </button>
          </div>
        </div>
      <p className="settings-note">As opções são aplicadas à próxima pesquisa. A chave fica apenas em memória e é apagada após iniciar ou trocar de provedor. Nada é salvo no navegador.</p>
    </fieldset>
  );
}

function useConsoleSnapshot() {
  const [snapshot, setSnapshot] = useState(null);
  const [connectionError, setConnectionError] = useState("");
  const alive = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch("/api/status", { cache: "no-store" });
      if (!response.ok)
        throw new Error(`O servidor respondeu HTTP ${response.status}.`);
      const data = await response.json();
      if (alive.current) {
        setSnapshot(data);
        setConnectionError("");
      }
    } catch (error) {
      if (alive.current) {
        setConnectionError(
          error.message || "Não foi possível conectar ao servidor local.",
        );
      }
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    refresh();
    const timer = window.setInterval(refresh, 1500);
    return () => {
      alive.current = false;
      window.clearInterval(timer);
    };
  }, [refresh]);

  return { snapshot, connectionError, refresh };
}

async function postJson(path, payload = {}) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      data.message || data.error || `Falha HTTP ${response.status}.`,
    );
  return data;
}

function getEventTitle(event) {
  if (event.type === "request") return "Requisição iniciada";
  if (event.type === "response") return "Resposta recebida";
  if (event.type === "campaign")
    return event.phase === "complete"
      ? "Pesquisa finalizada"
      : "Pesquisa iniciada";
  if (event.type === "error" || event.type === "agent_error")
    return "Etapa com erro";
  if (event.type === "denied") return "Ação fora do escopo";
  if (event.type === "control" || event.type === "stop")
    return "Controle da pesquisa";
  if (event.type === "triage") return "Achado classificado";
  if (event.check) return CHECK_LABELS[event.check] || event.check;
  if (event.agent) return event.agent;
  if (event.phase) return PHASE_LABELS[event.phase] || event.phase;
  return event.type || "Registro";
}

function getEventDetail(event) {
  const details = [];
  if (event.message) details.push(event.message);
  if (event.method && event.url) details.push(`${event.method} ${event.url}`);
  if (event.outcome) details.push(`Resultado observado: ${event.outcome}`);
  if (Number.isInteger(event.status)) details.push(`HTTP ${event.status}`);
  if (Number.isInteger(event.elapsed_ms))
    details.push(`${event.elapsed_ms} ms`);
  if (event.family)
    details.push(
      `Tecnologia identificada: ${event.family}${event.version ? ` ${event.version}` : ""}`,
    );
  if (event.finding_id) {
    details.push(
      `Achado ${event.finding_id}${event.severity ? ` · ${event.severity}` : ""}${event.confidence ? ` · confiança ${event.confidence}` : ""}`,
    );
  }
  if (event.difficulty_counts) {
    details.push(
      `Desafios encontrados: nível 1 (${event.difficulty_counts["1"] ?? 0}), nível 2 (${event.difficulty_counts["2"] ?? 0})`,
    );
  }
  return details.join(" · ") || "Registro recebido do pipeline.";
}

function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleTimeString("pt-BR", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
}

function Insight({ event }) {
  const kind =
    event.type === "triage"
      ? "finding"
      : event.type === "test"
        ? "test"
        : "note";
  return (
    <article className={`insight insight-${kind}`}>
      <span className="insight-mark" aria-hidden="true" />
      <div className="insight-content">
        <div className="insight-heading">
          <strong>{getEventTitle(event)}</strong>
          <time dateTime={event.timestamp}>{formatTime(event.timestamp)}</time>
        </div>
        {event.severity && <div className="event-classification">
          <span className={`severity ${event.severity.toLowerCase()}`}>{SEVERITY_LABELS[event.severity] || event.severity}</span>
          {event.status && <span>{FINDING_STATES[event.status] || event.status}</span>}
        </div>}
        <p>{getEventDetail(event)}</p>
      </div>
    </article>
  );
}

function SplashScreen({ onDone }) {
  const [leaving, setLeaving] = useState(false);
  const finish = useCallback(() => setLeaving(true), []);
  useLayoutEffect(() => {
    const root = document.documentElement;
    const wasLocked = root.classList.contains("splash-active");
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    root.classList.add("splash-active");
    return () => {
      if (!wasLocked) {
        root.classList.remove("splash-active");
        window.scrollTo(scrollX, scrollY);
      }
    };
  }, []);
  useEffect(() => {
    // Fallback: se o vídeo não disparar/terminar, encerra sozinho.
    const timer = window.setTimeout(finish, 9000);
    return () => window.clearTimeout(timer);
  }, [finish]);
  useEffect(() => {
    if (!leaving) return;
    const timer = window.setTimeout(onDone, 480);
    return () => window.clearTimeout(timer);
  }, [leaving, onDone]);
  // Fora da transição da página: um ancestral com transform prende position: fixed ao conteúdo.
  return createPortal(
    <div className={`splash${leaving ? " splash-leaving" : ""}`} role="presentation"
      onClick={finish}>
      <video className="splash-video" src="/video/splash.mp4"
        autoPlay muted playsInline preload="auto"
        onEnded={finish} onError={finish} />
      <button type="button" className="splash-skip" onClick={finish}>Pular</button>
    </div>,
    document.body,
  );
}

function App() {
  const { snapshot, connectionError, refresh } = useConsoleSnapshot();
  const [selectedPhase, setSelectedPhase] = useState(null);
  const [target, setTarget] = useState("");
  const [activeTarget, setActiveTarget] = useState("");
  const [view, setView] = useState(currentPage);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [noticeError, setNoticeError] = useState(false);
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [provider, setProvider] = useState("openai");
  const [region, setRegion] = useState("");
  const [severityFilter, setSeverityFilter] = useState("all");
  const [eventFilter, setEventFilter] = useState("all");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [pendingScan, setPendingScan] = useState(false);
  const [showSplash, setShowSplash] = useState(true);
  const dismissSplash = useCallback(() => setShowSplash(false), []);
  const [history, setHistory] = useState(null);
  const [historyError, setHistoryError] = useState("");
  const [historyAttempt, setHistoryAttempt] = useState(0);
  const [historyLimit, setHistoryLimit] = useState(6);
  const [savedRunId, setSavedRunId] = useState(() => window.location.hash.slice(6));
  const [savedResult, setSavedResult] = useState(null);
  const [savedError, setSavedError] = useState("");
  const [savedAttempt, setSavedAttempt] = useState(0);
  const [eventLimit, setEventLimit] = useState(30);
  const initializedTarget = useRef(false);
  const initializedModel = useRef(false);
  const navigate = useCallback((page) => {
    window.location.hash = page;
    setView(page);
  }, []);

  useEffect(() => {
    const onHashChange = () => {
      setView(currentPage());
      setSavedRunId(window.location.hash.slice(6));
      setEventFilter("all");
      setSeverityFilter("all");
      setEventLimit(30);
      setSettingsOpen(false);
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    const pageTitle = view === "home" ? "Análise de segurança com IA" : PAGES.find(([id]) => id === view)?.[1];
    document.title = `NA MIRA | ${pageTitle || "Análise de segurança com IA"}`;
  }, [view]);

  const reviewing = view === "test";
  const scope = snapshot?.scope || {};
  const result = (reviewing ? savedResult : snapshot?.result) || {};
  const observability = reviewing ? result.observability : snapshot?.observability;
  const events = reviewing ? result.actions || [] : snapshot?.events?.length
    ? snapshot.events
    : result.actions || [];
  const findings = result.findings || [];
  const recommendations = result.recommendations || [];
  const approvals = (reviewing ? [] : snapshot?.approvals || []).filter(
    (item) => item.status === "pending",
  );
  const running = !reviewing && Boolean(snapshot?.running);
  const state = running
    ? snapshot?.stop_requested
      ? "stopping"
      : "running"
    : result.status || (!reviewing && snapshot?.error ? "failed" : "idle");
  const filteredEvents = events
    .filter((event) => INSIGHT_TYPES.has(event.type))
    .filter((event) => eventFilter === "all" ||
      (eventFilter === "errors" ? ["error", "agent_error", "denied"].includes(event.type) : event.type === eventFilter));
  const insightEvents = [...filteredEvents].reverse()
    .sort((a, b) => (Date.parse(b.timestamp) || 0) - (Date.parse(a.timestamp) || 0))
    .slice(0, eventLimit);
  const visibleFindings = findings.filter((finding) =>
    severityFilter === "all" || finding.severity?.toLowerCase() === severityFilter);
  const activePhase = [...events].reverse().find((event) => event.phase)?.phase;
  const displayTarget = result.target || activeTarget || scope.target || "";
  const classified = running
    ? [...new Map(events.filter((event) => event.type === "triage" && event.finding_id)
        .map((event) => [event.finding_id, event])).values()]
    : findings;

  useEffect(() => {
    if (view !== "home") return undefined;
    const controller = new AbortController();
    setHistoryError("");
    getJson("/api/history", controller.signal).then(setHistory).catch((error) => {
      if (!controller.signal.aborted) setHistoryError(error.message || "Não foi possível carregar o histórico.");
    });
    return () => controller.abort();
  }, [view, snapshot?.running, historyAttempt]);

  useEffect(() => {
    if (!reviewing) return undefined;
    const controller = new AbortController();
    setSavedResult(null);
    setSavedError("");
    getJson(`/api/history/${encodeURIComponent(savedRunId)}`, controller.signal)
      .then((data) => { if (!controller.signal.aborted) setSavedResult({...data.result, observability: data.observability, executions: data.executions, hypotheses: data.hypotheses, evidence_catalog: data.evidence_catalog, conclusions: data.conclusions, verification_summary: data.verification_summary}); })
      .catch((error) => {
        if (!controller.signal.aborted) setSavedError(error.message || "Não foi possível abrir o teste.");
      });
    return () => controller.abort();
  }, [reviewing, savedRunId, savedAttempt]);

  useEffect(() => {
    if (!initializedTarget.current && scope.target) {
      setTarget(scope.target);
      initializedTarget.current = true;
    }
  }, [scope.target]);

  useEffect(() => {
    if (!initializedModel.current && snapshot?.scope) {
      setProvider(scope.ai_provider || "openai");
      setModel(scope.ai_model || "");
      initializedModel.current = true;
    }
  }, [snapshot?.scope, scope.ai_model, scope.ai_provider]);

  useEffect(() => {
    if (snapshot?.running) {
      setActiveTarget(snapshot.scope?.target || "");
    }
  }, [snapshot?.running, snapshot?.scope?.target]);

  useEffect(() => {
    if (view !== "research" || !running) return undefined;
    const frame = window.requestAnimationFrame(() => {
      document.getElementById("pipeline-title")?.scrollIntoView({
        block: "start",
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [view, running]);

  const perform = async (action) => {
    setBusy(true);
    setNotice("");
    setNoticeError(false);
    try {
      const response = await action();
      setNotice(response?.message || "");
      await refresh();
      return true;
    } catch (error) {
      const message = error.message || "A ação não foi concluída.";
      setNotice(message);
      setNoticeError(true);
      if (message.toLowerCase().includes("chave openai")) {
        setPendingScan(true);
        setSettingsOpen(true);
      }
      return false;
    } finally {
      setBusy(false);
    }
  };

  const startCampaign = async (event) => {
    if (event?.preventDefault) event.preventDefault();
    const requestedTarget = target.trim();
    setActiveTarget(requestedTarget);
    setNotice("");
    const started = await perform(() =>
      postJson("/api/campaign/start", {
        target_url: requestedTarget,
        authorization_confirmed: true,
        ai_provider: provider,
        api_key: apiKey,
        ai_model: model.trim(),
        aws_region: provider === "bedrock" ? region.trim() : "",
      }),
    );
    if (started) {
      setApiKey("");
      setPendingScan(false);
      setSettingsOpen(false);
      navigate("research");
    }
  };

  // Ao fechar as configurações: se a varredura ficou pendente por falta de
  // chave e a chave foi preenchida, retoma a varredura e vai para a análise.
  const closeSettings = () => {
    setSettingsOpen(false);
    if (pendingScan && apiKey.trim()) {
      setPendingScan(false);
      startCampaign();
    } else {
      setPendingScan(false);
    }
  };

  const decide = (approvalId, approve) =>
    perform(() =>
      postJson("/api/approval/decision", { approval_id: approvalId, approve }),
    );

  const stopCampaign = () => perform(() => postJson("/api/campaign/stop"));

  const returnHome = () => {
    navigate("home");
    setNotice("");
    setNoticeError(false);
    setApiKey("");
  };

  const changeProvider = (value) => {
    setProvider(value);
    setApiKey("");
    setModel(value === "bedrock" ? "amazon.nova-micro-v1:0" : "gpt-6-luna");
  };
  const aiSettings = (
    <AISettings provider={provider} onProviderChange={changeProvider}
      model={model} setModel={setModel} apiKey={apiKey} setApiKey={setApiKey}
      region={region} setRegion={setRegion} disabled={busy || Boolean(snapshot?.running) || !snapshot} />
  );
  const layout = (content) => (
    <ConsoleLayout view={view} state={state} assessment={observability?.assessment_status || result.assessment_status} connected={Boolean(snapshot) && !connectionError} onNewSearch={returnHome}>
      {connectionError && <div className="message error global-message" role="alert">{connectionError} Verifique o servidor local.</div>}
      {snapshot?.error && <div className="message error global-message" role="alert">{snapshot.error}</div>}
      {notice && <div className={`message global-message ${noticeError ? "error" : "success"}`} role={noticeError ? "alert" : "status"}>{notice}</div>}
      {approvals.length > 0 && view !== "research" && <a className="approval-link" href="#research">{approvals.length} aprovação(ões) pendente(s). Revisar no acompanhamento <ArrowRight className="inline-icon" aria-hidden="true" /></a>}
      {view !== "home" && result.run_id && <AssessmentStatus execution={running ? "running" : observability?.execution_status || result.execution_status || state}
        assessment={observability?.assessment_status || result.assessment_status} demo={result.demo} />}
      {content}
      {settingsOpen && <SettingsModal onClose={closeSettings} pendingScan={pendingScan}>{aiSettings}</SettingsModal>}
      {showSplash && <SplashScreen onDone={dismissSplash} />}
    </ConsoleLayout>
  );

  if (["settings", "reports"].includes(view)) {
    return layout(
      <main className="content-page">
        <p className="eyebrow">{view === "settings" ? "Preparação da varredura" : "Transparência da campanha"}</p>
        <h1>{view === "settings" ? "Configuração do projeto." : "Da evidência ao relatório."}</h1>
        <p className="page-description">{view === "settings" ? "Defina como o agente trabalha e confira todos os limites de segurança antes de iniciar uma varredura." : "Exporte os dados registrados, incluindo limitações e recomendações."}</p>
        {view === "settings" && <div className="project-config-stack">
          <section className="settings-panel project-config-section">
            <header className="project-section-heading">
              <span aria-hidden="true">01</span>
              <div><h2>Inteligência artificial</h2><p>Escolha o provedor e o modelo usados para planejar a análise e organizar as evidências. A IA não altera o alvo nem os limites abaixo.</p></div>
            </header>
            {aiSettings}
          </section>
          <section className="project-config-section scope-settings-panel">
            <header className="project-section-heading">
              <span aria-hidden="true">02</span>
              <div><h2>Escopo e limites</h2><p>Estas regras vêm da API e protegem o alvo contra uma execução ampla demais. Elas são apenas informativas nesta tela.</p></div>
            </header>
            <dl className="scope-grid">
              <div><dt>Alvo configurado</dt><dd>{scope.target || "Aguardando API"}</dd><small>Origem HTTPS autorizada para a próxima execução.</small></div>
              <div><dt>Orçamento de requisições</dt><dd>{scope.max_requests ?? "Não informado"}</dd><small>Total máximo de chamadas que a campanha pode realizar.</small></div>
              <div><dt>Intervalo mínimo</dt><dd>{scope.min_interval_seconds != null ? `${scope.min_interval_seconds} s` : "Não informado"}</dd><small>Pausa obrigatória entre chamadas para reduzir impacto no alvo.</small></div>
              <div><dt>Métodos permitidos</dt><dd>{scope.allowed_methods?.join(", ") || "Não informado"}</dd><small>Somente métodos de leitura, sem alterar dados do sistema avaliado.</small></div>
              <div><dt>Tempo limite</dt><dd>{scope.timeout_seconds != null ? `${scope.timeout_seconds} s` : "Não informado"}</dd><small>Espera máxima por cada resposta antes de seguir o fluxo.</small></div>
              <div><dt>Limite por resposta</dt><dd>{scope.max_response_bytes != null ? `${scope.max_response_bytes} bytes` : "Não informado"}</dd><small>Quantidade máxima de conteúdo lida em uma única resposta.</small></div>
            </dl>
            <div className="info-panel"><h2>Autorização não é opcional</h2><p>Use somente URLs HTTPS públicas que você tem autorização para avaliar. A IA orienta a análise; não confirma exploração nem amplia o escopo.</p></div>
          </section>
          <a className="primary-link" href="#home">Preparar nova varredura <ArrowRight className="inline-icon" aria-hidden="true" /></a>
        </div>}
        {view === "reports" && <>
          <div className="summary-grid">
            <div><span>Estado da campanha</span><strong>{STATUS_LABELS[state] || state}</strong></div>
            <div><span>Achados registrados</span><strong>{snapshot ? findings.length : "—"}</strong></div>
            <div><span>Eventos disponíveis</span><strong>{snapshot ? events.length : "—"}</strong></div>
          </div>
          {snapshot?.report_available ? <section className="info-panel">
            <h2>Relatório disponível</h2><p className="target-label">{displayTarget}</p>
            <nav className="download-options" aria-label="Baixar resultados">
              <a href="/api/report.md"><strong>Relatório Markdown <ArrowDownToLine className="inline-icon" aria-hidden="true" /></strong><span>Leitura, evidências e recomendações</span></a>
              <a href="/api/report.json"><strong>Dados JSON <ArrowDownToLine className="inline-icon" aria-hidden="true" /></strong><span>Dados estruturados para integração</span></a>
            </nav>
            <p className="settings-note">Durante uma execução, o download pode corresponder à última campanha salva. Confira o alvo e o run_id do arquivo.</p>
          </section> : <div className="empty-insights"><p>Nenhum relatório disponível.</p><small>Inicie uma pesquisa autorizada e acompanhe a conclusão.</small><a href="#home">Preparar pesquisa <ArrowRight className="inline-icon" aria-hidden="true" /></a></div>}
        </>}
      </main>,
    );
  }

  if (view === "executions") {
    return layout(<main className="content-page"><ExecutionHistory executions={snapshot?.executions} hypotheses={snapshot?.hypotheses} evidenceCatalog={snapshot?.evidence_catalog} conclusions={snapshot?.conclusions} verificationSummary={snapshot?.verification_summary} /></main>);
  }
  if (view === "home") {
    return layout(
      <main className="home search-home">
        <div className="center-brand">
          <h1 className="home-logo"><img src="/images/logo-home.png" alt="Na Mira" width="2579" height="1508" /></h1>
        </div>
        <div className="search-area">
          <form className="search-form" onSubmit={startCampaign}>
            <label className="visually-hidden" htmlFor="target-url">
              URL para pesquisar
            </label>
            <input
              id="target-url"
              type="url"
              autoComplete="url"
              placeholder="Cole a URL para pesquisar"
              value={target}
              onChange={(event) => setTarget(event.target.value)}
              required
              disabled={busy || running}
            />
            <div className="search-tools">
              <button
                type="button"
                className="settings-trigger"
                aria-label="Configurações da pesquisa"
                title="Configurações"
                onClick={() => setSettingsOpen(true)}
                aria-haspopup="dialog"
                disabled={busy}
              >
                <SettingsIcon aria-hidden="true" />
              </button>
              <button
                type="submit"
                className="search-submit"
                aria-label="Iniciar varredura"
                disabled={busy || running || !snapshot}
              >
                {busy ? <LoaderCircle className="icon-spinner" aria-hidden="true" /> : <ScanLine aria-hidden="true" />}
              </button>
            </div>
          </form>
          {running && <p className="running-note">Já existe uma pesquisa em andamento. <a href="#research">Acompanhar pesquisa <ArrowRight className="inline-icon" aria-hidden="true" /></a></p>}
        </div>
        <section className="history-section" aria-labelledby="history-title">
          <div className="section-title"><h2 id="history-title">Pesquisas recentes</h2><span>Salvas neste servidor</span></div>
          {historyError ? <div className="message error" role="alert">{historyError} <button type="button" onClick={() => setHistoryAttempt((value) => value + 1)}>Tentar novamente</button></div>
            : !history ? <p className="history-empty" role="status">Carregando histórico…</p>
              : <>
                {history.warnings?.length > 0 && <p className="message error" role="alert">{history.warnings.join(" ")}</p>}
                {history.runs.length ? <div className="history-grid">
                  {history.runs.slice(0, historyLimit).map((run) => (
                    <a className="history-tile" href={`#test/${run.run_id}`} key={run.run_id} title={run.target}>
                      <span className={`history-state status-${run.status}`}><span className="status-dot" />{run.assessment_status && run.assessment_status !== "complete" ? `Análise ${assessmentLabel(run.assessment_status).toLowerCase()}` : STATUS_LABELS[run.status] || run.status}</span>
                      <strong>{run.demo ? run.campaign_name : run.target}</strong>
                      {run.demo && <small>Demonstração · Docker real · fixtures locais</small>}
                      <span>{formatDate(run.started_at)}</span>
                      <span className="history-tile-footer">{run.findings_count} achado(s)<span aria-hidden="true"><ArrowUpRight size={16} /></span></span>
                    </a>
                  ))}
                </div> : <p className="history-empty">Seu próximo teste começa aqui. As pesquisas salvas aparecerão abaixo da busca.</p>}
                {history.runs.length > historyLimit && <button className="load-more" type="button" onClick={() => setHistoryLimit((value) => value + 6)}>Ver mais pesquisas</button>}
              </>}
        </section>
      </main>
    );
  }

  if (reviewing && !savedResult) {
    return layout(<main className="content-page">
      <a href="#home"><ArrowLeft className="inline-icon" aria-hidden="true" /> Histórico de pesquisas</a>
      <h1>{savedError ? "Não foi possível abrir o teste." : "Abrindo teste salvo…"}</h1>
      {savedError && <div className="message error" role="alert">{savedError}<button type="button" onClick={() => setSavedAttempt((value) => value + 1)}>Tentar novamente</button></div>}
    </main>);
  }

  return layout(
    <main className="research-page">
      {reviewing && <a className="back-history" href="#home"><ArrowLeft className="inline-icon" aria-hidden="true" /> Histórico de pesquisas</a>}
      {reviewing && result.demo && <section className="info-panel"><h2>{result.campaign_name}</h2>
        <p>Três hipóteses de fixtures, diagnóstico real do Docker e controle de autorização. Abra as verificações abaixo para consultar stdout, stderr e revisões.</p>
        <a href={`/api/history/${encodeURIComponent(result.run_id)}/report.md`}>Baixar relatório da demonstração <ArrowDownToLine className="inline-icon" /></a>
      </section>}
      {reviewing && <details><summary>Verificações e hipóteses desta campanha</summary><ExecutionHistory executions={result.executions} hypotheses={result.hypotheses} evidenceCatalog={result.evidence_catalog} conclusions={result.conclusions} verificationSummary={result.verification_summary} /></details>}
      <section className="research-intro">
        <div>
          <p className="eyebrow">
            {reviewing ? `Teste salvo · ${formatDate(result.started_at)}` : running ? "Pesquisa em andamento" : "Resultados da pesquisa"}
          </p>
          <h1>{view === "findings" ? "Evidências para revisar." : running ? "Acompanhe cada etapa." : "Pipeline da pesquisa."}</h1>
          <p className="target-label">{displayTarget || "URL não informada"}</p>
        </div>
        {running && (
          <button
            className="stop-button"
            type="button"
            onClick={stopCampaign}
            disabled={busy || snapshot?.stop_requested}
          >
            {snapshot?.stop_requested ? "Parada solicitada" : "Parar pesquisa"}
          </button>
        )}
      </section>

      <div className="research-meta">
        <span>
          {activePhase
            ? `Etapa atual: ${PHASE_LABELS[activePhase] || activePhase}`
            : running
              ? "Aguardando os primeiros registros…"
              : STATUS_LABELS[state]}
        </span>
        <span>{reviewing ? "Registro histórico · não envia novas requisições" : "Atualização automática a cada 1,5 s"}</span>
      </div>

      {(view === "research" || reviewing) && (
        <>
          <AgentPipeline events={events} running={running} state={state}
            target={displayTarget}
            maxRequests={result.summary?.scope?.max_requests ?? scope.max_requests}
            reportAvailable={reviewing || Boolean(snapshot?.report_available)}
            observability={observability}
            selectedPhase={selectedPhase}
            onSelectPhase={(id) => setSelectedPhase((prev) => (prev === id ? null : id))} />
          {observability?.mode === "v2" && (
            <XaiPanel observability={observability} events={events} result={result}
              conclusions={reviewing ? result.conclusions : snapshot?.conclusions}
              selectedPhase={selectedPhase} onSelect={setSelectedPhase} running={running} />
          )}
        </>
      )}

      {(view === "findings" || reviewing) && (
        <section className="classification-summary" aria-label="Classificação dos achados">
          {Object.entries(SEVERITY_LABELS).map(([severity, label]) => (
            <div key={severity}><span className={`severity ${severity}`}>{label}</span>
              <strong>{classified.filter((item) => item.severity?.toLowerCase() === severity).length}</strong></div>
          ))}
          <p>{running ? "Classificações recebidas da triagem. Novos registros aparecem no topo." : "A classificação indica a prioridade de revisão, não prova exploração."}</p>
        </section>
      )}

      {approvals.length > 0 && (
        <section className="approval-panel">
          <div>
            <p className="eyebrow">Decisão pendente</p>
            <h2>Ação aguardando aprovação</h2>
            {approvals.map((item) => (
              <p className="approval-reason" key={item.id}>
                {item.action_id}: {item.reason}
              </p>
            ))}
          </div>
          <div className="approval-actions">
            {approvals.map((item) => (
              <React.Fragment key={item.id}>
                <button
                  type="button"
                  className="approve-button"
                  disabled={busy}
                  onClick={() => decide(item.id, true)}
                >
                  Aprovar
                </button>
                <button
                  type="button"
                  className="reject-button"
                  disabled={busy}
                  onClick={() => decide(item.id, false)}
                >
                  Negar
                </button>
              </React.Fragment>
            ))}
          </div>
        </section>
      )}

      {(view === "research" || reviewing) && <details className="audit-panel">
        <summary>
          <span><strong>Log da auditoria</strong><small>Detalhes técnicos, requisições e decisões da campanha</small></span>
          <span className="audit-summary-meta"><span className="insight-count">{filteredEvents.length}</span><span className="audit-chevron" aria-hidden="true" /></span>
        </summary>
        <section className="insights-section audit-content" aria-live="polite" aria-relevant="additions">
        <label className="filter-field">Exibir eventos
          <select value={eventFilter} onChange={(event) => setEventFilter(event.target.value)}>
            <option value="all">Todos os registros</option>
            <option value="test">Verificações</option>
            <option value="triage">Classificações</option>
            <option value="errors">Erros e ações negadas</option>
          </select>
        </label>
        {insightEvents.length ? (
          <div className="insights-list">
            {insightEvents.map((event) => (
              <Insight
                key={`${event.timestamp || ""}-${event.type}-${event.check || event.agent || event.finding_id || event.url || event.message || ""}`}
                event={event}
              />
            ))}
          </div>
        ) : (
          <div className="empty-insights">
            <span
              className={running ? "waiting-pulse" : "empty-icon"}
              aria-hidden="true"
            >
              {running ? "" : <CircleHelp size={20} aria-hidden="true" />}
            </span>
            <p>
              {running
                ? "Aguardando os primeiros dados da pesquisa…"
                : "Nenhum registro corresponde a esta visualização."}
            </p>
            <small>
              Os insights são exibidos conforme chegam da API; nenhum resultado
              é presumido.
            </small>
          </div>
        )}
        {filteredEvents.length > eventLimit && <button type="button" className="load-more" onClick={() => setEventLimit((value) => value + 30)}>Mostrar registros anteriores</button>}
        </section>
      </details>}

      {(view === "findings" || reviewing) && (
        <section className="findings-section">
          <div className="section-title">
            <div>
              <p className="eyebrow">Classificação</p>
              <h2>Achados</h2>
            </div>
            <span className="insight-count">{findings.length}</span>
          </div>
          <label className="filter-field">Severidade
            <select value={severityFilter} onChange={(event) => setSeverityFilter(event.target.value)}>
              <option value="all">Todas as severidades</option>
              <option value="critical">Crítica</option>
              <option value="high">Alta</option>
              <option value="medium">Média</option>
              <option value="low">Baixa</option>
              <option value="info">Informativa</option>
            </select>
          </label>
          {visibleFindings.length === 0 && <div className="empty-insights">
            <p>{findings.length ? "Nenhum achado com esta severidade." : running ? "A análise dos achados está em andamento." : "Nenhum achado registrado nesta campanha."}</p>
            <small>{running ? "Acompanhe as classificações acima. Os detalhes ficam disponíveis quando o resultado chegar." : "A ausência de achados não garante a segurança do alvo."}</small>
          </div>}
          <div className="finding-list">
            {[...visibleFindings].reverse().map((finding, index) => (
              <article className="finding-card" key={finding.id || index}>
                <ConclusionReview compact conclusion={(reviewing ? result.conclusions : snapshot?.conclusions)?.find(c => c.subject_type === 'finding' && c.subject_id === finding.id)} />
                <div className="finding-heading">
                  <strong>
                    {finding.title ||
                      finding.check ||
                      finding.id ||
                      "Achado sem título"}
                  </strong>
                  <span
                    className={`severity ${(finding.severity || "info").toLowerCase()}`}
                  >
                    {SEVERITY_LABELS[finding.severity] || finding.severity || "—"}
                  </span>
                </div>
                <p>
                  {finding.impact ||
                    finding.evidence ||
                    "Sem detalhes registrados."}
                </p>
                <small>
                  {FINDING_STATES[finding.status] || finding.status || "estado não informado"}
                  {finding.confidence
                    ? ` · confiança ${finding.confidence}`
                    : ""}
                </small>
                {finding.recommendation && (
                  <p className="recommendation">
                    Recomendação: {finding.recommendation}
                  </p>
                )}
              </article>
            ))}
          </div>
        </section>
      )}

      {(view === "findings" || reviewing) && recommendations.length > 0 && (
        <section className="recommendations">
          <p className="eyebrow">Orientações</p>
          <h2>Próximos passos sugeridos</h2>
          <ul>
            {recommendations.map((item, index) => (
              <li key={item.finding_id || index}>
                {item.guidance ||
                  item.title ||
                  item.recommendation ||
                  JSON.stringify(item)}
              </li>
            ))}
          </ul>
        </section>
      )}

      {!reviewing && snapshot?.report_available && (
        <nav className="report-links" aria-label="Baixar resultados">
          <a href="#findings">Revisar achados ({findings.length}) <ArrowRight className="inline-icon" aria-hidden="true" /></a>
          <a href="#reports">Ver relatórios <ArrowRight className="inline-icon" aria-hidden="true" /></a>
        </nav>
      )}
      <p className="safety-note">
        Os resultados refletem apenas evidências e eventos registrados nesta
        campanha autorizada.
      </p>
    </main>
  );
}

function BrandGlyph() {
  return (
    <svg viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <path
        d="M5 11V5h6M21 5h6v6M27 21v6h-6M11 27H5v-6"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="square"
      />
      <circle cx="16" cy="16" r="3" fill="currentColor" />
      <path
        d="M16 8v3M24 16h-3M16 24v-3M8 16h3"
        stroke="currentColor"
        strokeWidth="1.4"
      />
    </svg>
  );
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
