import { App } from "../App";
import { Landing } from "./Landing";
import { PricingPage } from "./PricingPage";

/** Страницы сайта по адресу: / — главная, /pricing — цены и оплата, /studio — студия (вход и работа). */
export function Site() {
  const path = window.location.pathname.replace(/\/+$/, "") || "/";
  // старые ссылки вида /#/products ведут в студию
  if (path === "/" && window.location.hash.startsWith("#/")) {
    window.location.replace(`/studio${window.location.hash}`);
    return null;
  }
  if (path === "/") return <Landing />;
  if (path === "/pricing") return <PricingPage />;
  return <App />;
}
