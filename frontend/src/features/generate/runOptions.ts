import { createContext, useContext } from "react";
import type { RunOptions } from "../../hooks/useActions";

/** Пожелания из строки «Опишите ваш товар…» — их подхватывают и кнопки «Сгенерировать» на карточках товаров. */
export const RunOptionsCtx = createContext<RunOptions>({});
export const useRunOptions = () => useContext(RunOptionsCtx);

export const MARKET_PILLS: [string, string, string][] = [
  ["", "Как в пресете", ""],
  ["wb", "Wildberries", "3:4"],
  ["ozon", "Ozon", "3:4"],
  ["ymarket", "Яндекс Маркет", "3:4"],
  ["avito", "Авито", "4:3"],
];
export const ASPECT_PILLS = ["", "3:4", "4:5", "1:1", "9:16", "4:3", "16:9"];
export const BATCH: [number, string][] = [[0, "Все недостающие кадры"], [4, "До 4 кадров"], [10, "До 10 кадров"],
  [25, "До 25 кадров"], [50, "До 50 кадров"], [100, "До 100 кадров"]];

export const SHORT_MARKET: Record<string, string> = { wb: "WB", ozon: "Ozon", ymarket: "Я.Маркет", avito: "Авито", custom: "своя" };
