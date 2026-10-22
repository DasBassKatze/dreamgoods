import { useEffect, useRef, useState } from "react";
import type { ProjectState } from "../api/types";

/** Уведомления о готовности кадров. Всегда: счётчик готовых кадров в заголовке вкладки, пока она в фоне, и сообщение
 *  в сервисе, когда генерация закончилась. Если включить колокольчик: ещё звуковой сигнал и — где браузер разрешает —
 *  системное уведомление. Системные уведомления браузеры дают только сайтам по HTTPS (или localhost); по адресу
 *  вида http://192.168.… остаются звук и счётчик. Включаются в каждом браузере отдельно (отметка в localStorage). */

const KEY = "dg-notify-ready";
const EVT = "dg-notify-change";

export const notifySupported = () => typeof window !== "undefined" && "Notification" in window;

function stored(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function notifyOn(): boolean {
  return stored();
}

/** Системные уведомления доступны и разрешены. */
export const systemNotify = () => notifySupported() && window.isSecureContext && Notification.permission === "granted";

/** on — со системными уведомлениями; basic — только звук и счётчик (нет HTTPS, браузер запретил или не умеет); off. */
export type NotifyResult = "on" | "basic" | "insecure" | "denied" | "off";

export async function setNotify(on: boolean): Promise<NotifyResult> {
  let res: NotifyResult = "off";
  if (on) {
    if (!notifySupported()) res = "basic";
    else if (!window.isSecureContext) res = "insecure";
    else {
      let perm = Notification.permission;
      try {
        if (perm === "default") perm = await Notification.requestPermission();
      } catch { /* старые браузеры */ }
      res = perm === "granted" ? "on" : "denied";
    }
    beep();                                            // заодно браузер «разрешит» звук после клика
  }
  try {
    localStorage.setItem(KEY, on ? "1" : "0");
  } catch { /* приватный режим — действует до перезагрузки */ }
  window.dispatchEvent(new Event(EVT));
  return res;
}

/** Состояние переключателя (общее для всех мест, где он показан). */
export function useNotifySwitch(): boolean {
  const [on, setOn] = useState(notifyOn);
  useEffect(() => {
    const f = () => setOn(notifyOn());
    window.addEventListener(EVT, f);
    window.addEventListener("focus", f);
    return () => {
      window.removeEventListener(EVT, f);
      window.removeEventListener("focus", f);
    };
  }, []);
  return on;
}

let audio: AudioContext | null = null;

/** Короткий двойной сигнал (без файлов — синтезируется браузером). */
function beep() {
  try {
    const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    audio = audio || new AC();
    const t0 = audio.currentTime;
    [0, 0.18].forEach((d, i) => {
      const o = audio!.createOscillator();
      const g = audio!.createGain();
      o.frequency.value = i ? 1046 : 784;
      g.gain.setValueAtTime(0.0001, t0 + d);
      g.gain.exponentialRampToValueAtTime(0.18, t0 + d + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + d + 0.16);
      o.connect(g).connect(audio!.destination);
      o.start(t0 + d);
      o.stop(t0 + d + 0.18);
    });
  } catch { /* звук недоступен */ }
}

function show(title: string, body: string, tag: string, sound = false) {
  if (!notifyOn()) return;
  if (sound) beep();
  if (!systemNotify()) return;
  try {
    const n = new Notification(title, { body, tag, icon: (document.querySelector("link[rel=icon]") as HTMLLinkElement | null)?.href });
    n.onclick = () => {
      window.focus();
      n.close();
    };
  } catch { /* некоторые мобильные браузеры не дают создавать уведомления со страницы */ }
}

const plural = (n: number) => (n % 10 === 1 && n % 100 !== 11 ? "кадр" : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? "кадра" : "кадров");

/** Следит за состоянием проекта: новые готовые кадры и окончание генерации. */
export function useReadyNotify(state: ProjectState | null, toast: (t: string, ms?: number) => void) {
  const prev = useRef<{ pid: number; done: number; review: number; busy: boolean } | null>(null);
  const batch = useRef({ done: 0, review: 0 });       // сколько готово за текущий запуск
  const unseen = useRef(0);                           // готово, пока вкладка была в фоне
  const baseTitle = useRef(document.title);

  useEffect(() => {
    const onVis = () => {
      if (!document.hidden) {
        unseen.current = 0;
        document.title = baseTitle.current;
      }
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  useEffect(() => {
    if (!state) return;
    const cur = { pid: state.project.id, done: state.totals.done, review: state.totals.review, busy: state.runner.busy };
    const p = prev.current;
    prev.current = cur;
    if (!p || p.pid !== cur.pid) {
      batch.current = { done: 0, review: 0 };
      return;
    }
    const added = Math.max(0, cur.done - p.done);
    const toReview = Math.max(0, cur.review - p.review);
    batch.current.done += added;
    batch.current.review += toReview;
    const name = state.project.name;

    if (added && document.hidden) {
      unseen.current += added;
      document.title = `(${unseen.current}) ${baseTitle.current}`;
      if (cur.busy) show(`Готово ${unseen.current} ${plural(unseen.current)}`, `Проект «${name}» — генерация продолжается`, `dg-ready-${cur.pid}`);
    }
    if (p.busy && !cur.busy) {                         // генерация закончилась
      const { done, review } = batch.current;
      batch.current = { done: 0, review: 0 };
      if (!done && !review) return;
      const text = `Генерация завершена: готово ${done} ${plural(done)}` + (review ? `, на ручной проверке ${review}` : "");
      toast(`${text}.`, 6000);
      show("Кадры готовы", `Проект «${name}». ${text}`, `dg-ready-${cur.pid}`, true);
    }
  }, [state, toast]);
}
