import { DocumentLink } from "../../desktop/DocumentLink";
import { useEffect, useState } from "react";
import { authApi } from "../../api/client";
import type { MyConsent } from "../../api/types";
import { useUI } from "../../components/ui";

/** Мои согласия: какие документы и в какой редакции приняты; необязательные можно дать или отозвать. */
export function ConsentsSection() {
  const ui = useUI();
  const [items, setItems] = useState<MyConsent[] | null>(null);
  useEffect(() => { authApi.consents().then((r) => setItems(r.items)).catch(() => setItems([])); }, []);
  const act = async (fn: () => Promise<{ items: MyConsent[] }>, msg: string) => {
    try {
      setItems((await fn()).items);
      ui.toast(msg);
    } catch (e) {
      ui.toast((e as Error).message, 6000);
    }
  };
  if (!items?.length) return null;
  return (
    <>
      <h2>Документы и согласия</h2>
      <div className="table-wrap"><table className="tbl">
        <thead><tr><th>Документ</th><th>Редакция</th><th>Согласие</th><th /></tr></thead>
        <tbody>{items.map((c) => (
          <tr key={c.kind}>
            <td><DocumentLink kind={c.kind}>{c.title}</DocumentLink>
              {!c.required && <span className="hint"> · необязательно</span>}</td>
            <td className="hint">{c.version}</td>
            <td>{c.granted
              ? <span>дано{c.at ? ` ${new Date(c.at).toLocaleDateString("ru-RU")}` : ""}{c.granted_version < c.version ? ` (редакция ${c.granted_version})` : ""}</span>
              : <span className="hint">нет</span>}</td>
            <td className="actions">{!c.required && (c.granted
              ? <button onClick={() => act(() => authApi.revokeConsent(c.kind), "Согласие отозвано")}>Отозвать</button>
              : <button onClick={() => act(() => authApi.acceptConsents([c.kind]), "Согласие дано")}>Дать согласие</button>)}</td>
          </tr>
        ))}</tbody>
      </table></div>
      <p className="hint">Обязательные согласия нужны для работы сервиса. Чтобы отозвать их и удалить учётную запись,
        напишите оператору сервиса — контакты указаны в <DocumentLink kind="privacy">политике</DocumentLink>.</p>
    </>
  );
}
