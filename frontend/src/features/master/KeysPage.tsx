import { useCallback, useEffect, useState } from "react";
import { adminApi } from "../../api/client";
import type { PolzaKeyView } from "../../api/types";
import { useUI } from "../../components/ui";
import { rub } from "../../lib/format";

/** Мастер: ключи API Polza. Общий пул + закрепление ключа за пользователем. */
export function KeysPage() {
  const ui = useUI();
  const [keys, setKeys] = useState<PolzaKeyView[] | null>(null);
  const [secret, setSecret] = useState("");
  const [name, setName] = useState("");

  const load = useCallback(async (refresh = false) => {
    try {
      setKeys((await adminApi.keys(refresh)).keys);
    } catch (e) {
      ui.toast((e as Error).message);
    }
  }, [ui]);
  useEffect(() => {
    load(true);
  }, [load]);

  const act = (fn: () => Promise<unknown>, msg?: string) => async () => {
    try {
      await fn();
      if (msg) ui.toast(msg);
      load();
    } catch (e) {
      ui.toast((e as Error).message);
    }
  };

  const add = act(async () => {
    await adminApi.createKey({ secret, name });
    setSecret("");
    setName("");
  }, "Ключ добавлен");

  const remove = (k: PolzaKeyView) => async () => {
    if (!(await ui.confirm({ text: `Удалить ключ «${k.name}»? Пользователи с ним перейдут на общий пул.`, ok: "Удалить", danger: true }))) return;
    act(() => adminApi.deleteKey(k.id), "Ключ удалён")();
  };

  return (
    <section className="page">
      <div className="page-head">
        <h1>Ключи Polza</h1>
        <span className="spacer" />
        <button onClick={() => load(true)}>Обновить балансы</button>
      </div>
      <p className="lead">Пользователь работает на закреплённом за ним ключе, а если такого нет — на одном из ключей общего пула
        (распределяются поровну, у каждого пользователя всегда один и тот же). Без ключей используется ключ из технических настроек.</p>

      <div className="key-add">
        <input type="text" placeholder="Название, например «Основной»" value={name} onChange={(e) => setName(e.target.value)} />
        <input type="password" className="grow" placeholder="Ключ API Polza" value={secret} onChange={(e) => setSecret(e.target.value)} />
        <button className="primary" disabled={secret.trim().length < 10} onClick={add}>Добавить ключ</button>
      </div>

      {!keys ? <div className="empty">Загрузка…</div> : !keys.length ? (
        <div className="empty">Ключей пока нет — генерации идут через ключ из технических настроек.</div>
      ) : (
        <div className="keys">
          {keys.map((k) => (
            <article key={k.id} className={`key ${k.active ? "" : "off"}`}>
              <header>
                <b>{k.name}</b><code>{k.mask}</code>
                <span className="spacer" />
                <span className={`key-bal ${k.balance_error ? "bad-text" : ""}`} title={k.balance_error}>
                  {k.balance == null ? (k.balance_error ? "ошибка ключа" : "…") : rub(k.balance)}</span>
              </header>
              <div className="key-flags">
                <label className="switch"><input type="checkbox" checked={k.active}
                  onChange={act(() => adminApi.updateKey(k.id, { active: !k.active }))} /><i /> включён</label>
                <label className="switch"><input type="checkbox" checked={k.shared}
                  onChange={act(() => adminApi.updateKey(k.id, { shared: !k.shared }))} /><i /> в общем пуле</label>
                <span className="spacer" />
                <button className="link danger" onClick={remove(k)}>Удалить</button>
              </div>
              <div className="hint">
                {k.serves.length ? <>Сейчас на нём: {k.serves.join(", ")}</> : "Сейчас никто не использует"}
                {k.pinned.length > 0 && <> · закреплён за: {k.pinned.join(", ")}</>}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
