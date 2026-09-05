import { useId, useRef, useState } from "react";
import type { MessageKey } from "../i18n";

interface DeviceCrossSectionProps {
  text: (key: MessageKey) => string;
}

/** Topology illustration only: these boundaries are not a solver mesh or field. */
export function DeviceCrossSection({ text }: DeviceCrossSectionProps) {
  const titleId = useId();
  const descriptionId = useId();
  const [selection, setSelection] = useState("all");
  const [zoom, setZoom] = useState(1);
  const [center, setCenter] = useState({ x: 400, y: 220 });
  const drag = useRef<{ x: number; y: number; cx: number; cy: number; scale: number; region: string | null } | null>(null);
  const regions: Array<[string, MessageKey]> = [
    ["all", "allRegions"], ["silicon", "silicon"], ["source", "source"],
    ["drain", "drain"], ["oxide", "oxide"], ["gate", "polysilicon"],
    ["source-contact", "sourceContact"], ["drain-contact", "drainContact"], ["body-contact", "bodyContact"],
  ];
  const move = (x: number, y: number, atZoom = zoom) => setCenter({
    x: Math.max(400 / atZoom, Math.min(800 - 400 / atZoom, x)),
    y: Math.max(220 / atZoom, Math.min(440 - 220 / atZoom, y)),
  });
  const changeZoom = (next: number) => { const value = Math.max(1, Math.min(4, next)); setZoom(value); move(center.x, center.y, value); };
  const reset = () => { setZoom(1); setCenter({ x: 400, y: 220 }); };

  return (
    <figure className="device-drawing">
      <div className="drawing-tools m4-toolbar">
        <label>{text("selectRegion")}<select value={selection} onChange={(event) => setSelection(event.target.value)}>
          {regions.map(([id, key]) => <option key={id} value={id}>{text(key)}</option>)}
        </select></label>
        <button type="button" className="quiet-button" disabled={zoom === 4} onClick={() => changeZoom(zoom + 0.5)}>{text("zoomIn")}</button>
        <button type="button" className="quiet-button" disabled={zoom === 1} onClick={() => changeZoom(zoom - 0.5)}>{text("zoomOut")}</button>
        <output aria-live="polite">{Math.round(zoom * 100)}%</output>
        <button type="button" className="quiet-button" onClick={reset}>{text("resetView")}</button>
        {([["panLeft", -1, 0, "←"], ["panRight", 1, 0, "→"], ["panUp", 0, -1, "↑"], ["panDown", 0, 1, "↓"]] as const).map(([key, x, y, icon]) =>
          <button key={key} type="button" className="quiet-button" disabled={zoom === 1} aria-label={text(key)} onClick={() => move(center.x + x * 40 / zoom, center.y + y * 40 / zoom)}>{icon}</button>)}
      </div>
      <div className="device-drawing-scroll" tabIndex={0} role="region" aria-label={text("crossSection")}
        onKeyDown={(event) => {
          const direction = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
          if (direction) { event.preventDefault(); move(center.x + direction[0] * 40 / zoom, center.y + direction[1] * 40 / zoom); }
          if (["+", "=", "-", "Home"].includes(event.key)) { event.preventDefault(); if (event.key === "Home") reset(); else changeZoom(zoom + (event.key === "-" ? -0.5 : 0.5)); }
        }}>
        <svg
          className="device-section-svg"
          viewBox={`${center.x - 400 / zoom} ${center.y - 220 / zoom} ${800 / zoom} ${440 / zoom}`}
          role="img"
          aria-labelledby={titleId}
          aria-describedby={descriptionId}
          onPointerDown={(event) => {
            if (event.button !== 0) return;
            const box = event.currentTarget.getBoundingClientRect();
            drag.current = { x: event.clientX, y: event.clientY, cx: center.x, cy: center.y,
              scale: Math.max(0.01, Math.min(box.width / (800 / zoom), box.height / (440 / zoom))),
              region: (event.target as Element).closest("[data-region]")?.getAttribute("data-region") ?? null };
            event.currentTarget.setPointerCapture?.(event.pointerId);
          }}
          onPointerMove={(event) => {
            if (!drag.current) return;
            const start = drag.current;
            move(start.cx - (event.clientX - start.x) / start.scale, start.cy - (event.clientY - start.y) / start.scale);
          }}
          onPointerUp={(event) => {
            const start = drag.current;
            if (start && Math.hypot(event.clientX - start.x, event.clientY - start.y) < 4) {
              const id = start.region;
              if (id && regions.some(([key]) => key === id)) setSelection(id);
            }
            drag.current = null;
            if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
          }}
          onPointerCancel={() => { drag.current = null; }}
          onLostPointerCapture={() => { drag.current = null; }}
        >
          <title id={titleId}>{text("deviceAria")}</title>
          <desc id={descriptionId}>{text("deviceDescription")}</desc>
          <g className="device-domain-lines" data-selection={selection}>
            <rect data-region="silicon" x="70" y="184" width="660" height="160" fill="#b9d9ec" />
            <path data-region="source" d="M100 184 H286 V221 Q286 250 256 250 H130 Q100 250 100 221 Z" fill="#386cb0" />
            <path data-region="drain" d="M514 184 H700 V221 Q700 250 670 250 H544 Q514 250 514 221 Z" fill="#386cb0" />
            <rect data-region="oxide" x="70" y="170" width="660" height="14" fill="#eee5b5" />
            <rect data-region="gate" x="300" y="100" width="200" height="70" fill="#d9a23e" />
            <rect data-region="source-contact" x="154" y="144" width="72" height="40" fill="#596a78" />
            <rect data-region="drain-contact" x="574" y="144" width="72" height="40" fill="#596a78" />
            <rect data-region="body-contact" x="358" y="344" width="84" height="14" fill="#596a78" />
          </g>
          <g className="device-leaders">
            <path d="M190 93 V141 M400 67 V97 M610 93 V141 M400 360 V378" />
            <path d="M507 177 H756 V125 H712" />
          </g>
          <g className="device-diagram-labels" textAnchor="middle">
            <text x="190" y="80">S · {text("source")}</text>
            <text x="400" y="54">G · {text("gate")}</text>
            <text x="610" y="80">D · {text("drain")}</text>
            <text x="400" y="141">{text("polysilicon")}</text>
            <text className="device-doped-label" x="193" y="222">n+</text>
            <text className="device-doped-label" x="607" y="222">n+</text>
            <text x="400" y="300">{text("pTypeSilicon")}</text>
            <text x="400" y="402">B · {text("substrate")}</text>
            <text x="701" y="118" textAnchor="end">SiO₂</text>
          </g>
        </svg>
      </div>
      <figcaption>{text("schematicNotice")}<p>{text("drawingHelp")}</p></figcaption>
    </figure>
  );
}
