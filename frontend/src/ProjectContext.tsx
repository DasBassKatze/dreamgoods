// Общий контекст экрана проекта: состояние с сервера, API проекта, выбор товаров.
import { createContext, useContext } from "react";
import type { ProjectApi } from "./api/client";
import type { Product, ProjectState } from "./api/types";

export interface ProjectScope {
  state: ProjectState;
  api: ProjectApi;
  reload: () => Promise<ProjectState | undefined>;
  selected: Set<number>;
  toggleSelected: (productId: number, on: boolean) => void;
  setSelected: (ids: number[]) => void;
  /** Выделенные кадры (для выгрузки только их). */
  pickedFrames: Set<number>;
  togglePicked: (frameId: number, on: boolean) => void;
  setPicked: (ids: number[]) => void;
  product: (id: number) => Product | undefined;
  /** Сколько кадров максимум ставить за один запуск (0 — без ограничения). */
  limit: number;
  setLimit: (n: number) => void;
  /** Обёртка действий: ловит ошибку и показывает её уведомлением. */
  run: (fn: () => Promise<unknown>) => Promise<void>;
}

export const ProjectCtx = createContext<ProjectScope | null>(null);

export function useProject(): ProjectScope {
  const s = useContext(ProjectCtx);
  if (!s) throw new Error("ProjectCtx не подключён");
  return s;
}
