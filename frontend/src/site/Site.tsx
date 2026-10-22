import { App } from "../App";
import { Landing } from "./Landing";
import { VerifyPage } from "../features/auth/VerifyPage";
import { LegalPage } from "./LegalPage";
import { PricingPage } from "./PricingPage";

/** Страницы сайта по адресу: / — главная, /pricing — цены и оплата, /legal/<вид> — документы, /verify — подтверждение
 *  почты по ссылке из письма, /studio — студия (вход, регистрация и работа). */
export function Site() {
  const path = window.location.pathname.replace(/\/+$/, "") || "/";
  // старые ссылки вида /#/products ведут в студию
  if (path === "/" && window.location.hash.startsWith("#/")) {
    window.location.replace(`/studio${window.location.hash}`);
    return null;
  }
  if (path === "/") return <Landing />;
  if (path === "/pricing") return <PricingPage />;
  if (path.startsWith("/legal/")) return <LegalPage kind={decodeURIComponent(path.slice(7))} />;
  if (path === "/verify") return <VerifyPage />;
  return <App />;
}
