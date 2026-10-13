import { createContext, useContext, useEffect, useRef, type ReactNode } from "react";

// открытые окна по порядку: Esc закрывает только верхнее
const stack: object[] = [];

/** Внутри PageMode окно-раздел (пресеты, модели, импорт…) рисуется как страница сайта, а не поверх него.
 *  Вложенные окна снова становятся обычными всплывающими. */
export const PageMode = createContext(false);

interface Props {
  title: ReactNode;
  onClose: () => void;
  width?: number;
  actions?: ReactNode; // кнопки в заголовке рядом с ✕
  footer?: ReactNode;
  children: ReactNode;
  closeOnEsc?: boolean;
}

export function Modal(props: Props) {
  return useContext(PageMode) ? <PagePanel {...props} /> : <Popup {...props} />;
}

function PagePanel({ title, actions, footer, children }: Props) {
  return (
    <PageMode.Provider value={false}>
      <section className="page">
        <div className="page-head">
          <h1>{title}</h1>
          <span className="spacer" />
          {actions}
        </div>
        <div className="page-body">{children}</div>
        {footer && <div className="row box-foot">{footer}</div>}
      </section>
    </PageMode.Provider>
  );
}

function Popup({ title, onClose, width = 1100, actions, footer, children, closeOnEsc = true }: Props) {
  const me = useRef({});
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const token = me.current;
    stack.push(token);
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape" && closeOnEsc && stack[stack.length - 1] === token) {
        e.stopImmediatePropagation();
        close.current();
      }
    };
    document.addEventListener("keydown", h);
    return () => {
      document.removeEventListener("keydown", h);
      stack.splice(stack.indexOf(token), 1);
    };
  }, [closeOnEsc]);

  return (
    <div className="modal" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="box" style={{ maxWidth: width }} role="dialog" aria-modal="true">
        <div className="row box-head">
          <b>{title}</b>
          <span className="spacer" />
          {actions}
          <button onClick={onClose} aria-label="Закрыть">✕</button>
        </div>
        {children}
        {footer && <div className="row box-foot">{footer}</div>}
      </div>
    </div>
  );
}
