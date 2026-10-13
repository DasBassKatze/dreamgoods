// Всплывающие уведомления и диалоги подтверждения/ввода — вместо alert/confirm/prompt браузера.
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { Modal } from "./Modal";

interface ConfirmOptions {
  title?: string;
  text: ReactNode;
  ok?: string;
  cancel?: string;
  danger?: boolean;
}

interface Choice<T extends string> {
  value: T;
  label: string;
  primary?: boolean;
}

interface Field {
  key: string;
  label: string;
  value?: string;
  type?: "text" | "password";
}

interface UI {
  toast: (text: string, ms?: number) => void;
  confirm: (o: ConfirmOptions) => Promise<boolean>;
  choose: <T extends string>(o: { title: string; text: ReactNode; choices: Choice<T>[] }) => Promise<T | null>;
  ask: (o: { title: string; fields: Field[]; ok?: string }) => Promise<Record<string, string> | null>;
}

const Ctx = createContext<UI | null>(null);

export const useUI = () => {
  const ui = useContext(Ctx);
  if (!ui) throw new Error("UIProvider не подключён");
  return ui;
};

type Dialog =
  | { kind: "choose"; title: string; text: ReactNode; choices: Choice<string>[]; resolve: (v: string | null) => void }
  | { kind: "ask"; title: string; fields: Field[]; ok: string; resolve: (v: Record<string, string> | null) => void };

export function UIProvider({ children }: { children: ReactNode }) {
  const [toastText, setToastText] = useState("");
  const toastTimer = useRef<number | undefined>(undefined);
  const [dialog, setDialog] = useState<Dialog | null>(null);

  const toast = useCallback((text: string, ms = 3200) => {
    setToastText(text);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToastText(""), ms);
  }, []);

  const choose = useCallback(
    <T extends string>(o: { title: string; text: ReactNode; choices: Choice<T>[] }) =>
      new Promise<T | null>((resolve) =>
        setDialog({ kind: "choose", ...o, resolve: resolve as (v: string | null) => void }),
      ),
    [],
  );

  const confirm = useCallback(
    async (o: ConfirmOptions) =>
      (await choose({
        title: o.title || "Подтверждение",
        text: o.text,
        choices: [
          { value: "no", label: o.cancel || "Отмена" },
          { value: "yes", label: o.ok || "OK", primary: true },
        ],
      })) === "yes",
    [choose],
  );

  const ask = useCallback(
    (o: { title: string; fields: Field[]; ok?: string }) =>
      new Promise<Record<string, string> | null>((resolve) =>
        setDialog({ kind: "ask", title: o.title, fields: o.fields, ok: o.ok || "OK", resolve }),
      ),
    [],
  );

  const value = useMemo(() => ({ toast, confirm, choose, ask }), [toast, confirm, choose, ask]);

  const close = (v: string | null | Record<string, string>) => {
    if (!dialog) return;
    (dialog.resolve as (x: typeof v) => void)(v);
    setDialog(null);
  };

  return (
    <Ctx.Provider value={value}>
      {children}
      {dialog?.kind === "choose" && (
        <Modal title={dialog.title} width={560} onClose={() => close(null)}
          footer={<>
            <span className="spacer" />
            {dialog.choices.map((c) => (
              <button key={c.value} className={c.primary ? "primary" : ""} autoFocus={c.primary} onClick={() => close(c.value)}>
                {c.label}
              </button>
            ))}
          </>}>
          <div className="dialog-text">{dialog.text}</div>
        </Modal>
      )}
      {dialog?.kind === "ask" && <AskDialog dialog={dialog} onDone={close} />}
      {toastText && <div className="toast">{toastText}</div>}
    </Ctx.Provider>
  );
}

function AskDialog({ dialog, onDone }: { dialog: Extract<Dialog, { kind: "ask" }>; onDone: (v: Record<string, string> | null) => void }) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(dialog.fields.map((f) => [f.key, f.value || ""])),
  );
  return (
    <Modal title={dialog.title} width={480} onClose={() => onDone(null)}
      footer={<>
        <span className="spacer" />
        <button onClick={() => onDone(null)}>Отмена</button>
        <button className="primary" type="submit" form="ask-form">{dialog.ok}</button>
      </>}>
      <form id="ask-form" className="form" onSubmit={(e) => { e.preventDefault(); onDone(values); }}>
        {dialog.fields.map((f, n) => (
          <label key={f.key} className="form-row">
            <span>{f.label}</span>
            <input type={f.type || "text"} autoFocus={n === 0} value={values[f.key]}
              onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} />
          </label>
        ))}
      </form>
    </Modal>
  );
}
