import { useId } from "react";
import type { MessageKey } from "../i18n";

interface DeviceCrossSectionProps {
  text: (key: MessageKey) => string;
}

/** Topology illustration only: these boundaries are not a solver mesh or field. */
export function DeviceCrossSection({ text }: DeviceCrossSectionProps) {
  const titleId = useId();
  const descriptionId = useId();

  return (
    <figure className="device-drawing">
      <div className="device-drawing-scroll" tabIndex={0} role="region" aria-label={text("crossSection")}>
        <svg
          className="device-section-svg"
          viewBox="0 0 800 440"
          role="img"
          aria-labelledby={titleId}
          aria-describedby={descriptionId}
        >
          <title id={titleId}>{text("deviceAria")}</title>
          <desc id={descriptionId}>{text("deviceDescription")}</desc>
          <g className="device-domain-lines">
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
      <figcaption>{text("schematicNotice")}</figcaption>
    </figure>
  );
}
