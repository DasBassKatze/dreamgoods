import { useEffect, useRef, useState } from "react";
import { projectApi } from "../../api/client";
import type { Route } from "../../hooks/useRoute";
import { Icon } from "../../layout/Icon";
import "./assistant.css";

export type AssistantAction = { type: "navigate"; route: Route; label: string }
  | { type: "product"; product_id: number; label: string };
export interface AssistantReply { answer: string; actions: AssistantAction[]; model: string; cost_rub: number }
export interface AssistantConfig { enabled: boolean; configured: boolean; model: string; routes: Partial<Record<Route, string>> }
type Turn = { role: "user" | "assistant"; content: string; actions?: AssistantAction[] };

interface Props {
  projectId: number;
  projectName: string;
  route: Route;
  selected: { id: number; sku: string }[];
  master: boolean;
  go: (route: Route) => void;
  openProduct: (id: number) => void;
}

export function AssistantPanel(p: Props) {
  const [open, setOpen] = useState(false);
  const [config, setConfig] = useState<AssistantConfig | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [configError, setConfigError] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const alive = useRef(true);
  const sending = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    if (!open) return;
    let current = true;
    setConfigError("");
    projectApi(p.projectId).assistantConfig().then(v => { if (current) setConfig(v); })
      .catch(e => { if (current) setConfigError((e as Error).message); });
    const timer = setTimeout(() => input.current?.focus(), 180);
    const escape = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); e.stopPropagation(); } };
    window.addEventListener("keydown", escape);
    return () => { current = false; clearTimeout(timer); window.removeEventListener("keydown", escape); };
  }, [open, p.projectId]);
  useEffect(() => { if (open && list.current) list.current.scrollTop = list.current.scrollHeight; }, [turns, busy, error, open]);

  const send = async (question = text) => {
    const message = question.trim();
    if (!message || sending.current || !config?.enabled || !config.configured) return;
    sending.current = true; setBusy(true); setError(""); setText("");
    const history: Turn[] = [];
    let size = 0;
    for (const turn of turns.slice(-10).reverse()) {
      if (size + turn.content.length > 16000) break;
      history.unshift(turn); size += turn.content.length;
    }
    setTurns(cur => [...cur, { role: "user" as const, content: message }].slice(-40));
    try {
      const result = await projectApi(p.projectId).askAssistant({ message, history: history.map(({ role, content }) => ({ role, content })),
        route: p.route, product_ids: p.selected.slice(0, 5).map(v => v.id) });
      if (alive.current) setTurns(cur => [...cur, { role: "assistant" as const, content: result.answer, actions: result.actions }].slice(-40));
    } catch (e) {
      if (alive.current) { setError((e as Error).message); setText(message); }
    } finally {
      sending.current = false;
      if (alive.current) { setBusy(false); input.current?.focus(); }
    }
  };

  const action = (a: AssistantAction) => {
    if (a.type === "navigate" && config?.routes[a.route] && (p.master || !a.route.startsWith("m-"))) {
      p.go(a.route);
      document.querySelector(".content")?.animate?.([{ opacity: .6, transform: "translateY(5px)" }, { opacity: 1, transform: "translateY(0)" }],
        { duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 200, easing: "ease-out" });
    } else if (a.type === "product" && p.selected.some(v => v.id === a.product_id)) {
      p.openProduct(a.product_id); setOpen(false);
    }
  };
  const ready = config?.enabled && config.configured;

  return <>
    <button className={`assistant-launch ${open ? "active" : ""}`} aria-label={open ? "Закрыть ИИ-помощника" : "Открыть ИИ-помощника"}
      aria-expanded={open} aria-controls="dg-assistant" onClick={() => setOpen(!open)}>
      <Icon name={open ? "close" : "spark"} size={22} /><span>Помощник</span>
    </button>
    <aside id="dg-assistant" className={`assistant-panel ${open ? "is-open" : ""}`} aria-label="ИИ-помощник DreamGoods"
      aria-hidden={!open} inert={!open}>
      <header className="assistant-head">
        <span className="assistant-mark"><Icon name="spark" size={23} /></span>
        <div><b>Ваш помощник</b><small>Подскажу следующий шаг</small></div>
        <span className="spacer" />
        <button aria-label="Новый диалог" title="Очистить диалог" disabled={busy} onClick={() => { setTurns([]); setError(""); setText(""); input.current?.focus(); }}><Icon name="regen" /></button>
        <button aria-label="Свернуть помощника" onClick={() => setOpen(false)}><Icon name="close" /></button>
      </header>
      <div className="assistant-context"><span className="assistant-dot" />{p.projectName}
        {p.selected.length > 0 && <span> · {p.selected.slice(0, 5).map(v => v.sku).join(", ")}{p.selected.length > 5 ? " · первые 5 товаров" : ""}</span>}
      </div>
      <div className="assistant-messages" ref={list} role="log" aria-live="polite" aria-relevant="additions">
        {!turns.length && <div className="assistant-welcome">
          <div className="assistant-orbit"><Icon name="spark" size={34} /></div>
          <h3>С чего начнём?</h3><p>Помогу разобраться с загрузкой, планом кадров и настройками. Вижу текущий раздел и выбранные товары.</p>
          {["Как загрузить товары?", "Как добавить референс в план кадров?", "Что делать после обрыва генерации?"].map(q =>
            <button key={q} disabled={!ready || busy} onClick={() => void send(q)}>{q}<span>↗</span></button>)}
        </div>}
        {turns.map((turn, i) => <div key={i} className={`assistant-turn ${turn.role}`}>
          <small>{turn.role === "user" ? "Вы" : "DreamGoods"}</small><div>{turn.content}</div>
          {!!turn.actions?.length && <div className="assistant-actions">{turn.actions.map((a, j) =>
            <button key={j} disabled={a.type === "product" && !p.selected.some(v => v.id === a.product_id)} onClick={() => action(a)}>{a.label} ↗</button>)}</div>}
        </div>)}
        {busy && <div className="assistant-thinking" role="status"><i /><i /><i /><span>Готовлю ответ…</span></div>}
        {(error || configError) && <div className="assistant-error" role="alert">{error || configError}</div>}
        {config && !config.enabled && <div className="assistant-error">Помощник выключен в технических настройках.</div>}
        {config && !config.configured && <div className="assistant-error">Для ответов ИИ нужен ключ Polza.
          {p.master ? <button onClick={() => p.go("m-keys")}>Открыть ключи Polza</button> : " Обратитесь к администратору."}</div>}
      </div>
      <form className="assistant-compose" onSubmit={e => { e.preventDefault(); void send(); }}>
        <label className="sr-only" htmlFor="assistant-question">Вопрос помощнику</label>
        <textarea id="assistant-question" ref={input} value={text} maxLength={3000} rows={2} placeholder="Например: как составить план кадров?"
          disabled={!ready || busy} onChange={e => setText(e.target.value)} onKeyDown={e => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); }
          }} />
        <button className="assistant-send" type="submit" disabled={!ready || busy || !text.trim()} aria-label="Отправить вопрос"><Icon name="upload" size={20} /></button>
        <small>Ответы ИИ платные · {config?.model || "Polza AI"}<br />Переходы — по кнопке. Диалог хранится только до смены проекта или закрытия приложения.</small>
      </form>
    </aside>
  </>;
}
