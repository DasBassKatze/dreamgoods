import { memo } from "react";
import { assetUrl } from "../api/client";
import type { Frame } from "../api/types";
import { badgeText, pad, qcStatus } from "../lib/format";

interface Props {
  frame: Frame;
  onOpen: () => void;
  onRegen: () => void;
}

function FrameTileImpl({ frame: f, onOpen, onRegen }: Props) {
  const q = qcStatus(f);
  const badge = badgeText(f);
  const title = f.error || (f.qc?.defects.length ? f.qc.defects.join("; ") : f.shot);
  return (
    <div className={`tile st-${f.state} ${q ? `q-${q}` : ""}`} title={title} onClick={onOpen}>
      {f.asset ? <img loading="lazy" src={assetUrl(f.asset, 360)} alt="" /> : <div className="ph">{pad(f.i)}</div>}
      {badge && <span className="badge">{badge}</span>}
      <div className="tools">
        <button title={f.asset ? "Перегенерировать" : "Сгенерировать"}
          onClick={(e) => { e.stopPropagation(); onRegen(); }}>↻</button>
      </div>
      <div className="cap">{pad(f.i)} · {f.block}</div>
    </div>
  );
}

// перерисовываем плитку только если изменился сам кадр (опрос сервера каждые 2–5 с)
export const FrameTile = memo(FrameTileImpl, (a, b) => JSON.stringify(a.frame) === JSON.stringify(b.frame));
