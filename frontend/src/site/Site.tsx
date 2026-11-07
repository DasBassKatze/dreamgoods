import { isDesktop } from "../desktop/runtime";
import { lazy, Suspense } from "react";
const App = lazy(() => import("../App").then((m) => ({ default: m.App })));
import { Landing } from "./Landing";
import { VerifyPage } from "../features/auth/VerifyPage";
import { LegalPage } from "./LegalPage";
const PricingPage = lazy(() => import("./PricingPage").then((m) => ({ default: m.PricingPage })));

/** Страницы сайта по адресу: / — главная, /pricing — цены и оплата, /legal/<вид> — документы, /verify — подтверждение
 *  почты по ссылке из письма, /studio — студия (вход, регистрация и работа). */
export function Site() {
  if (isDesktop) return <Suspense fallback={<div className="empty">Загрузка…</div>}><App /></Suspense>;
  const path = window.location.pathname.replace(/\/+$/, "") || "/";
  // старые ссылки вида /#/products ведут в студию
  if (path === "/" && window.location.hash.startsWith("#/")) {
    window.location.replace(`/studio${window.location.hash}`);
    return null;
  }
  if (path === "/") return <Landing />;
  if (path === "/pricing") return <Suspense fallback={<div className="empty">Загрузка…</div>}><PricingPage /></Suspense>;
  if (path.startsWith("/legal/")) return <LegalPage kind={decodeURIComponent(path.slice(7))} />;
  if (path === "/verify") return <VerifyPage />;
  return <Suspense fallback={<div className="empty">Загрузка…</div>}><App /></Suspense>;
}

