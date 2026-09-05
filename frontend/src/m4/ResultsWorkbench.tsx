import { useId, useState, type Dispatch, type SetStateAction } from "react";
import type { MessageKey } from "../i18n";
import { decodeWorkspaceText, downloadWorkspaceJson, readWorkspaceBytes } from "./files";
import { resultExamples } from "./examples";
import { compatibleResults, parseResult, resultFingerprint, sampleDifference,
  type CurveResult, type ImportedResult, type StructureResult } from "./results";

const colors = ["#68e7dc", "#ffcb6a"];
const materials = ["#b9d9ec", "#386cb0", "#d9a23e", "#9e6ea6", "#5a8c72", "#b45c5c"];
let nextImportId = 0;
const number = (value: number) => Number.isInteger(value) && Math.abs(value) < 10000 ? String(value) : value.toPrecision(4);
type Text = (key: MessageKey) => string;

function CurvePlot({ records, text }: { records: ImportedResult[]; text: Text }) {
  const curves = records.map((record) => record.data as CurveResult);
  const points = curves.flatMap((curve) => curve.points);
  const log = curves[0].kind === "profile";
  const yValue = (y: number) => log ? Math.log10(y) : y;
  const xMin = Math.min(...points.map(([x]) => x)), xMax = Math.max(...points.map(([x]) => x));
  const values = points.map(([, y]) => yValue(y));
  let yMin = Math.min(...values), yMax = Math.max(...values);
  if (yMin === yMax) { const padding = Math.max(Math.abs(yMin) * 0.05, 1e-12); yMin -= padding; yMax += padding; }
  const x = (value: number) => 98 + (value - xMin) / (xMax - xMin) * 584;
  const y = (value: number) => 300 - (yValue(value) - yMin) / (yMax - yMin) * 258;
  const difference = curves.length === 2 ? sampleDifference(curves[0], curves[1]) : null;
  return <>
    <div className="result-plot-scroll" tabIndex={0} role="region" aria-label={text("importedComparison")}>
      <svg className="result-plot" viewBox="0 0 720 360" role="img" aria-label={text(curves[0].kind === "iv" ? "importedIv" : "importedProfile")}>
        {[0, 1, 2, 3, 4].map((tick) => <g key={tick}>
          <path d={`M98 ${300 - tick * 64.5} H682 M${98 + tick * 146} 42 V300`} className="result-grid-line" />
          <text x="88" y={306 - tick * 64.5} textAnchor="end">{log ? `10^${number(yMin + (yMax - yMin) * tick / 4)}` : number(yMin + (yMax - yMin) * tick / 4)}</text>
          <text x={98 + tick * 146} y="325" textAnchor="middle">{number(xMin + (xMax - xMin) * tick / 4)}</text>
        </g>)}
        <text x="98" y="25">{curves[0].yUnit}{log ? " (log₁₀)" : ""}</text>
        <text x="682" y="351" textAnchor="end">{curves[0].xUnit}</text>
        {curves.map((curve, index) => <polyline key={records[index].id}
          points={curve.points.map(([px, py]) => `${x(px)},${y(py)}`).join(" ")}
          fill="none" stroke={colors[index]} strokeWidth="2.5" strokeDasharray={index ? "7 4" : undefined} />)}
      </svg>
    </div>
    <ul className="result-key">{records.map((record, index) => <li key={record.id} style={{ color: colors[index] }}>{index + 1}. {record.data.name}</li>)}</ul>
    {curves.length === 2 && <div className="comparison-metrics" role="status">
      {difference ? <dl>
        <div><dt>{text("matchingSamples")}</dt><dd>{difference.count}</dd></div>
        <div><dt>{text("maxDifference")}</dt><dd>{number(difference.maxAbsolute)} {curves[0].yUnit}</dd></div>
        <div><dt>{text("meanDifference")}</dt><dd>{number(difference.meanAbsolute)} {curves[0].yUnit}</dd></div>
      </dl> : <p>{text("unmatchedSamples")}</p>}
    </div>}
    <p className="m4-help">{text("noAcceptance")}</p>
    <details className="sample-details"><summary>{text("sampleTable")}</summary>
      {curves.map((curve, index) => <div className="sample-table" key={records[index].id} tabIndex={0}>
        <table><caption>{curve.name}</caption><thead><tr><th scope="col">{curve.xUnit}</th><th scope="col">{curve.yUnit}</th></tr></thead>
          <tbody>{curve.points.map(([px, py], row) => <tr key={row}><td>{px}</td><td>{py}</td></tr>)}</tbody>
        </table>
      </div>)}
    </details>
  </>;
}

function StructurePlot({ record, text, world, palette }: { record: ImportedResult; text: Text; world: { width: number; height: number }; palette: string[] }) {
  const data = record.data as StructureResult;
  const materialNames = [...new Set(data.regions.map((region) => region.material))];
  const scale = Math.min(600 / world.width, 320 / world.height);
  return <section className="imported-structure">
    <h3>{data.name}</h3>
    <svg viewBox="0 0 640 370" role="img" aria-label={`${text("importedStructure")}: ${data.name}`}>
      <rect x="20" y="20" width={data.width * scale} height={data.height * scale} fill="#eaf1f6" stroke="#273d4f" />
      {data.regions.map((region) => <rect key={region.id} x={20 + region.x * scale} y={20 + region.y * scale}
        width={region.width * scale} height={region.height * scale}
        fill={materials[palette.indexOf(region.material) % materials.length]} stroke="#152c40" strokeWidth="1">
        <title>{region.id}: {region.material}</title>
      </rect>)}
      <text x="20" y="363">{data.width} × {data.height} μm</text>
    </svg>
    <ul className="result-key">{materialNames.map((material) => <li key={material}>
      <i style={{ backgroundColor: materials[palette.indexOf(material) % materials.length] }} aria-hidden="true" />{material}
    </li>)}</ul>
    <details className="sample-details"><summary>{text("structureRegions")}</summary><div className="sample-table" tabIndex={0}>
      <table><thead><tr>{["ID", text("material"), "x", "y", text("sourceWidth"), text("sourceHeight")].map((heading) => <th scope="col" key={heading}>{heading}</th>)}</tr></thead>
        <tbody>{data.regions.map((region) => <tr key={region.id}>{[region.id, region.material, region.x, region.y, region.width, region.height].map((value, index) => <td key={index}>{value}</td>)}</tr>)}</tbody>
      </table>
    </div></details>
  </section>;
}

interface Props { records: ImportedResult[]; onChange: Dispatch<SetStateAction<ImportedResult[]>>; text: Text }
export function ResultsWorkbench({ records, onChange, text }: Props) {
  const idPrefix = useId();
  const [reading, setReading] = useState(false);
  const [error, setError] = useState<MessageKey | null>(null);
  const [selection, setSelection] = useState<string[]>([]);
  const selected = records.filter((record) => selection.includes(record.id));
  const structures = selected.map((record) => record.data).filter((data): data is StructureResult => data.kind === "structure");
  const world = { width: Math.max(...structures.map((data) => data.width)), height: Math.max(...structures.map((data) => data.height)) };
  const palette = [...new Set(structures.flatMap((data) => data.regions.map((region) => region.material)))].sort();
  const toggle = (record: ImportedResult) => {
    if (selection.includes(record.id)) { setSelection(selection.filter((id) => id !== record.id)); setError(null); return; }
    if (selected.length >= 2 || (selected[0] && !compatibleResults(selected[0].data, record.data))) { setError("compareLimit"); return; }
    setSelection([...selected.map((item) => item.id), record.id]); setError(null);
  };
  return <section className="panel results-workbench" aria-label={text("importResults")}>
    <div className="panel-header"><div><h2>{text("importResults")}</h2><p>{text("unverifiedImport")}</p></div></div>
    <div className="results-body">
      <p className="m4-help">{text("resultsHelp")}</p>
      <details className="sample-details"><summary>{text("resultFormats")}</summary>
        <p className="m4-help">{text("resultFormatsHelp")}</p>
        <code>vd_v,id_ma_per_um</code><br /><code>depth_um,concentration_cm-3</code>
        <div className="m4-toolbar">{resultExamples.map((example) => <button key={example.kind} type="button" className="quiet-button" onClick={() => {
          try { downloadWorkspaceJson(`${JSON.stringify(example, null, 2)}\n`, `opentcad-example-${example.kind}.json`); }
          catch { setError("invalidFile"); }
        }}>{text(example.kind === "iv" ? "exampleIv" : example.kind === "profile" ? "exampleProfile" : "exampleStructure")}</button>)}</div>
      </details>
      <label className="file-field">{text("importResults")}
        <input type="file" accept=".json,.csv,application/json,text/csv" disabled={reading || records.length >= 8}
          onChange={async (event) => {
            const file = event.target.files?.[0]; event.target.value = "";
            if (!file) return;
            if (records.length >= 8) { setError("resultLimit"); return; }
            setReading(true); setError(null);
            try {
              const bytes = await readWorkspaceBytes(file);
              const source = decodeWorkspaceText(bytes);
              const data = parseResult(source, file.name);
              const record: ImportedResult = { id: `${idPrefix}-${++nextImportId}`, filename: file.name,
                sha256: await resultFingerprint(bytes), data, verified: false };
              onChange((current) => current.length < 8 ? [...current, record] : current);
              if (!selected.length) setSelection([record.id]);
            } catch { setError("invalidFile"); }
            finally { setReading(false); }
          }} />
      </label>
      {records.length >= 8 && <p role="status">{text("resultLimit")}</p>}
      {reading && <p role="status">{text("readingFile")}</p>}
      {error && <p role="alert">{text(error)}</p>}
      {!records.length && <p className="result-empty">{text("resultsEmpty")}</p>}
      <div className="result-records" role="group" aria-label={text("compareSelection")}>
        {records.map((record) => <article key={record.id} className="result-record">
          <label><input type="checkbox" checked={selection.includes(record.id)} disabled={reading} onChange={() => toggle(record)} />
            {text("selectResult")}: {record.data.name}</label>
          <span className="unverified-label">{text("unverifiedImport")}</span>
          <dl><div><dt>{text("fileName")}</dt><dd>{record.filename}</dd></div>
            <div><dt>{text("sourceClaim")}</dt><dd>{record.data.source}</dd></div>
            <div><dt>SHA-256</dt><dd>{record.sha256 ?? text("hashUnavailable")}</dd></div></dl>
          <button type="button" className="quiet-button" disabled={reading} aria-label={`${text("removeResult")}: ${record.data.name}`} onClick={() => {
            onChange((current) => current.filter((item) => item.id !== record.id)); setSelection(selection.filter((id) => id !== record.id)); setError(null);
          }}>{text("removeResult")}</button>
        </article>)}
      </div>
      {!!records.length && <p className="m4-help">{text("hashNotice")}</p>}
      {!!selected.length && <section className="imported-comparison" aria-label={text("importedComparison")}>
        <h3>{text("importedComparison")}</h3>
        {selected[0].data.kind === "structure"
          ? <><div className="structure-comparison">{selected.map((record) => <StructurePlot record={record} text={text} world={world} palette={palette} key={record.id} />)}</div><p>{text("noAcceptance")}</p></>
          : <CurvePlot records={selected} text={text} />}
      </section>}
    </div>
  </section>;
}
