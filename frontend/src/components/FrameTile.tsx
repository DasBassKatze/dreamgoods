import { memo } from "react";
import { assetUrl, downloadUrl } from "../api/client";
import type { Frame } from "../api/types";
import { Icon } from "../layout/Icon";
import { badgeText, pad, qcStatus } from "../lib/format";

interface Props {
  frame: Frame;
  /** имя файла при скачивании: «артикул_03» */
  fileName: string;
  /** формат кадров товара, «3:4» — плитка той же формы */
  aspect: string;
  /** плашка площадки и формата: «WB · 3:4» */
  label: string;
  focused: boolean;
  onFocus: () => void;
  onOpen: () => void;
  onRegen: () => void;
  onUpscale: () => void;
  picked: boolean;
  onPick: (on: boolean) => void;
}

function FrameTileImpl({ frame: f, fileName, aspect, label, focused, onFocus, onOpen, onRegen, onUpscale, picked, onPick }: Props) {
  const q = qcStatus(f);
  const badge = badgeText(f);
  const title = f.error || (f.qc?.defects.length ? f.qc.defects.join("; ") : f.shot);
  const stop = (fn: () => void) => (e: React.MouseEvent) => { e.stopPropagation(); fn(); };
  return (
    <div className={`tile st-${f.state} ${q ? `q-${q}` : ""} ${picked ? "picked" : ""} ${focused ? "focused" : ""}`} title={title}
      tabIndex={0} role="group" aria-label={`Кадр ${f.i}: ${badge || f.block}`}
      onKeyDown={e => { if (e.target === e.currentTarget && ["Enter", " "].includes(e.key)) { e.preventDefault(); if (e.shiftKey) onOpen(); else onFocus(); } }}
      style={{ aspectRatio: aspect.replace(":", "/") }}
      onClick={(e) => ((e.ctrlKey || e.metaKey) && f.asset ? onPick(!picked) : onFocus())} onDoubleClick={onOpen}>
      {f.asset ? <img loading="lazy" src={assetUrl(f.asset, 480)} alt="" /> : <div className="ph">{pad(f.i)}</div>}
      {badge ? <span className="badge">{badge}</span> : label && f.asset ? <span className="badge mk">{label}</span> : null}
      <div className="cap">{pad(f.i)} · {f.block}</div>
      <div className="hover-bar" onClick={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
        {f.asset && (
          <a className="hb" href={downloadUrl(f.asset, fileName)} title="Скачать оригинал"><Icon name="download" size={16} /></a>
        )}
        {f.asset && <button className="hb" title="Улучшить до 4K" onClick={stop(onUpscale)}><Icon name="upscale" size={16} /></button>}
        {f.asset && <button className="hb" title="Редактировать" onClick={stop(onOpen)}><Icon name="edit" size={16} /></button>}
        <button className="hb" title={f.asset ? "Перегенерировать" : "Сгенерировать"} onClick={stop(onRegen)}><Icon name="regen" size={16} /></button>
      </div>
      {f.asset && (
        <label className="pick" title="Выделить кадр — для выгрузки только выделенных (или Ctrl+клик по кадру)"
          onClick={(e) => e.stopPropagation()}>
          <input type="checkbox" aria-label={`Выделить кадр ${f.i} для скачивания`} checked={picked} onChange={(e) => onPick(e.target.checked)} />
        </label>
      )}
    </div>
  );
}

// перерисовываем плитку только если изменился сам кадр (опрос сервера каждые 2–5 с)
export const FrameTile = memo(FrameTileImpl,
  (a, b) => a.picked === b.picked && a.focused === b.focused && a.label === b.label && a.aspect === b.aspect
    && JSON.stringify(a.frame) === JSON.stringify(b.frame));
