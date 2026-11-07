import { DocumentLink } from "../../desktop/DocumentLink";
import { isDesktop } from "../../desktop/runtime";
import { useCallback, useEffect, useState } from "react";
import { adminApi } from "../../api/client";
import type { ConsentRow, LegalAdmin } from "../../api/types";
import { useUI } from "../../components/ui";

const SOURCE: Record<string, string> = { register: "регистрация", login: "при входе", account: "кабинет", persona: "модель", master: "мастер" };
const when = (s: string | null) => (s ? new Date(s).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" }) : "—");

/** Мастер: тексты документов (версии), регистрация на сайте, журнал согласий. */
export function LegalPage() {
  const ui = useUI();
  const [data, setData] = useState<LegalAdmin | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [draft, setDraft] = useState({ title: "", body: "", required: true });
  const [rows, setRows] = useState<ConsentRow[]>([]);
  const [kind, setKind] = useState("");
  const [q, setQ] = useState("");

  const load = useCallback(() => adminApi.legal().then(setData).catch((e) => ui.toast((e as Error).message)), [ui]);
  const loadJournal = useCallback(() => adminApi.consents(kind, q).then((r) => setRows(r.items)).catch(() => {}), [kind, q]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { const t = window.setTimeout(loadJournal, 250); return () => window.clearTimeout(t); }, [loadJournal]);

  const edit = (k: string) => {
    const d = data?.docs.find((x) => x.kind === k);
    if (!d) return;
    setOpen(open === k ? null : k);
    setDraft({ title: d.title, body: d.body, required: d.required });
  };
  const save = async (k: string) => {
    const d = data?.docs.find((x) => x.kind === k);
    if (d?.required && draft.required && d.where === "register" && !(await ui.confirm({
      title: "Новая редакция", ok: "Сохранить",
      text: "Это обязательный документ: после сохранения все пользователи при следующем входе увидят новую редакцию и должны будут принять её заново.",
    }))) return;
    try {
      setData(await adminApi.saveLegal(k, draft.title, draft.body, draft.required));
      setOpen(null);
      ui.toast("Сохранено — новая редакция опубликована");
      loadJournal();
    } catch (e) {
      ui.toast((e as Error).message);
    }
  };
  const toggleReg = async () => {
    if (!data) return;
    setData(await adminApi.setRegistration(!data.registration_open));
    ui.toast(data.registration_open ? "Регистрация на сайте закрыта" : "Регистрация на сайте открыта");
  };

  return (
    <section className="page">
      <div className="page-head"><h1>Документы и согласия</h1></div>
      {data && !isDesktop && (
        <div className="legal-top">
          <label className="check"><input type="checkbox" checked={data.registration_open} onChange={toggleReg} />
            {" "}регистрация на сайте открыта</label>
          <span className={data.mail ? "hint" : "tag warn"}>{data.mail
            ? "почта для писем настроена"
            : "⚠ почта (SMTP) не настроена: письма не уходят, ссылка подтверждения — в журнале сервера; почту можно подтвердить вручную в «Пользователях»"}</span>
        </div>
      )}
      <p className="hint">Тексты — черновики, их нужно согласовать с юристом. Сохранение создаёт новую редакцию; принятые
        редакции и время согласия хранятся в журнале ниже. Обязательные документы регистрации пользователи принимают
        заново при следующем входе.</p>
      <div className="legal-docs">
        {data?.docs.map((d) => (
          <div key={d.kind} className="legal-doc-card">
            <div className="row">
              <b>{d.title}</b>
              <span className="tag">редакция {d.version}</span>
              {d.required ? <span className="tag">обязательный</span> : <span className="hint">необязательный</span>}
              <span className="hint">{d.where === "persona" ? "при загрузке фото модели" : "при регистрации"} · согласий: {d.consents}</span>
              {d.body.startsWith("ЧЕРНОВИК") && <span className="tag warn">черновик</span>}
              <span className="spacer" />
              <DocumentLink kind={d.kind}>открыть</DocumentLink>
              <button onClick={() => edit(d.kind)}>{open === d.kind ? "Свернуть" : "Изменить"}</button>
            </div>
            {open === d.kind && (
              <div className="legal-edit">
                <input type="text" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
                <textarea value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
                <div className="row">
                  <span className="hint">«# текст» — подзаголовок, «- текст» — пункт списка</span>
                  <span className="spacer" />
                  {d.kind !== "persona_photo" && (
                    <label className="check"><input type="checkbox" checked={draft.required}
                      onChange={(e) => setDraft({ ...draft, required: e.target.checked })} /> обязательный</label>)}
                  <button onClick={() => setOpen(null)}>Отмена</button>
                  <button className="primary" onClick={() => save(d.kind)}>Сохранить новую редакцию</button>
                </div>
                {d.versions.length > 1 && <div className="hint">Редакции: {d.versions.map((v) => `${v.version} (${when(v.at)})`).join(", ")}</div>}
              </div>
            )}
          </div>
        ))}
      </div>

      <h2>Журнал согласий</h2>
      <div className="row">
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">все документы</option>
          {data?.docs.map((d) => <option key={d.kind} value={d.kind}>{d.title}</option>)}
        </select>
        <input type="search" placeholder="логин или имя модели" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="spacer" />
        <a className="btn" href={adminApi.consentsCsvUrl(kind, q)}>Скачать CSV</a>
      </div>
      <div className="table-wrap"><table className="tbl">
        <thead><tr><th>Когда</th><th>Логин</th><th>Документ</th><th>Ред.</th><th>Действие</th><th>Где</th><th>Чьё / к чему</th><th>IP</th></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.id}>
            <td className="hint">{when(r.at)}</td>
            <td>{r.email || "—"}</td>
            <td>{r.title}</td>
            <td className="num">{r.version}</td>
            <td className={r.granted ? "" : "bad-text"}>{r.granted ? "согласие" : "отзыв"}</td>
            <td className="hint">{SOURCE[r.source] || r.source}</td>
            <td className="hint">{r.subject}{r.ref ? ` · ${r.ref}` : ""}</td>
            <td className="hint" title={r.agent}>{r.ip}</td>
          </tr>
        ))}
        {!rows.length && <tr><td colSpan={8} className="hint">Записей нет</td></tr>}
        </tbody>
      </table></div>
    </section>
  );
}
