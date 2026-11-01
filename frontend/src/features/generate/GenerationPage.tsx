import { useEffect, useState } from "react";
import type { Dialogs } from "../../App";
import { Header } from "../../components/Header";
import { LogPanel } from "../../components/LogPanel";
import { ProductList } from "../../components/ProductList";
import { ProjectBar } from "../../components/ProjectBar";
import { ListBar, Toolbar, type Filter } from "../../components/Toolbar";
import type { RunOptions } from "../../hooks/useActions";
import { useProject } from "../../ProjectContext";
import { StagePanel } from "../workflow/StagePanel";
import { Composer } from "./Composer";
import { FrameDetails } from "./FrameDetails";
import { RunOptionsCtx } from "./runOptions";

interface Props {
  dialogs: Dialogs;
  filter: Filter;
  onFilter: (f: Filter) => void;
  onProjectsChanged: () => void;
}

/** Вкладка «Генерация»: строка запуска, настройки съёмки, товары с кадрами и детали выбранного кадра справа. */
export function GenerationPage({ dialogs, filter, onFilter, onProjectsChanged }: Props) {
  const { state, product } = useProject();
  // пожелания, площадка и формат задаются в пресете — у запуска своих настроек нет
  const opts: RunOptions = {};
  const [query, setQuery] = useState("");
  const [focus, setFocus] = useState<{ productId: number; frameId: number } | null>(null);
  // кадр удалили или пересобрали — панель деталей закрывается
  const alive = focus && product(focus.productId)?.frames.some((f) => f.id === focus.frameId);
  useEffect(() => {
    if (focus && !alive) setFocus(null);
  }, [focus, alive]);
  useEffect(() => setFocus(null), [state.project.id]);

  return (
    <RunOptionsCtx.Provider value={opts}>
      <Header dialogs={dialogs} onProjectsChanged={onProjectsChanged} query={query} onQuery={setQuery} />
      <div className="gen-top">
        <div className="gen-setup">
          <ProjectBar dialogs={dialogs} />
          <Composer />
        </div>
      </div>
      <StagePanel />
      <Toolbar filter={filter} onFilter={onFilter} />
      <div className="layout">
        <div className="main-col">
          <ListBar />
          <ProductList filter={filter} query={query} dialogs={dialogs} focus={focus?.frameId ?? null}
            onFocus={(productId, frameId) => {
              // на узком экране панель деталей далеко внизу — сразу открываем кадр целиком
              if (window.matchMedia("(max-width: 1000px)").matches) dialogs.openFrame(productId, frameId);
              else setFocus(focus?.frameId === frameId ? null : { productId, frameId });
            }} />
        </div>
        <aside>
          {focus && alive ? (
            <FrameDetails productId={focus.productId} frameId={focus.frameId}
              onOpen={() => dialogs.openFrame(focus.productId, focus.frameId)} onClose={() => setFocus(null)} />
          ) : (
            <div className="panel det-empty">
              <b>Детали изображения</b>
              <span>Нажмите на кадр, чтобы увидеть параметры, скачать, улучшить или отредактировать его. Двойной клик — открыть целиком.</span>
            </div>
          )}
          <LogPanel />
        </aside>
      </div>
    </RunOptionsCtx.Provider>
  );
}

