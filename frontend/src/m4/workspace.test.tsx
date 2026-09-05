import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { en, ko } from "../i18n";
import { newProject, serializeProject } from "./project";
import type { ImportedResult } from "./results";
import { ResultsWorkbench } from "./ResultsWorkbench";

const curve = (name: string, offset = 0) => ({ format: "opentcad-result", schemaVersion: 1,
  kind: "iv", name, source: "unreviewed source", xUnit: "V", yUnit: "mA/um",
  points: [[0, offset], [0.5, 0.1 + offset], [1, 0.2 + offset]] });
const resultFile = (name: string, offset = 0) => new File([JSON.stringify(curve(name, offset))], `${name}.json`, { type: "application/json" });
const resultInput = () => screen.getByLabelText(en.importResults, { selector: "input" });

beforeEach(() => {
  window.localStorage.clear(); window.history.replaceState(null, "", "/#workspace");
  vi.stubGlobal("fetch", vi.fn());
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("M4 project editing", () => {
  it("requires an explicit replacement after import and preserves the current project on errors", async () => {
    const user = userEvent.setup(); render(<App />);
    fireEvent.change(screen.getByLabelText(en.projectName), { target: { value: "Unsaved work" } });
    const project = { ...newProject(), name: "Imported project", deck: newProject().deck + "# imported\n" };
    await user.upload(screen.getByLabelText(en.openProject), new File([serializeProject(project)], "project.json", { type: "application/json" }));
    expect(await screen.findByRole("button", { name: en.applyProject })).toBeEnabled();
    expect(screen.getByLabelText(en.projectName)).toHaveValue("Unsaved work");
    await user.click(screen.getByRole("button", { name: en.discardImport }));
    expect(screen.getByLabelText(en.projectName)).toHaveValue("Unsaved work");
    await user.upload(screen.getByLabelText(en.openProject), new File([serializeProject(project)], "project.json", { type: "application/json" }));
    await user.click(await screen.findByRole("button", { name: en.applyProject }));
    expect(screen.getByLabelText(en.projectName)).toHaveValue("Imported project");
    expect(screen.getByRole("textbox", { name: en.deckAria })).toHaveValue(project.deck);
    await user.upload(screen.getByLabelText(en.openProject), new File(['{"name":1,"name":2}'], "bad.json", { type: "application/json" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(en.invalidFile);
    expect(screen.getByLabelText(en.projectName)).toHaveValue("Imported project");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("downloads a project explicitly and reports invalid editable bias values", async () => {
    const create = vi.fn(() => "blob:project"), revoke = vi.fn();
    const OriginalURL = URL;
    vi.stubGlobal("URL", class extends OriginalURL { static createObjectURL = create; static revokeObjectURL = revoke; });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: en.saveProject }));
    expect(create).toHaveBeenCalledTimes(1);
    expect(screen.getByText(en.projectSaved)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: en.device }));
    fireEvent.change(screen.getByLabelText(`${en.temperature} (K)`), { target: { value: "0" } });
    expect(screen.getByRole("button", { name: en.saveProject })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: en.process }));
    expect(screen.getByRole("button", { name: en.runReference })).toBeDisabled();
    expect(screen.getByText(en.projectInvalid)).toBeVisible();
  });

  it("links an invalid deck diagnostic to its editable line and blocks mock start", () => {
    render(<App />);
    const editor = screen.getByRole("textbox", { name: en.deckAria }) as HTMLTextAreaElement;
    fireEvent.change(editor, { target: { value: 'initialize silicon orientation=100\ngrid x=0 spacing=0\nstructure output="x.str"' } });
    expect(screen.getByRole("button", { name: en.runReference })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: new RegExp(`Line 2.*${en.deckNumeric.slice(0, 20)}`) }));
    expect(editor).toHaveFocus(); expect(editor.selectionStart).toBe(editor.value.indexOf("grid"));
    expect(editor).toHaveAttribute("aria-invalid", "true");
  });
});

describe("M4 mock lifecycle and device exploration", () => {
  it.each([false, true])("recovers and cancels mock work without a runtime request, local=%s", (local) => {
    vi.useFakeTimers(); render(<App localBootstrap={local ? { token: "A".repeat(43) } : null} />);
    fireEvent.click(screen.getByRole("button", { name: en.runReference }));
    act(() => { vi.advanceTimersByTime(620); });
    fireEvent.click(screen.getByRole("button", { name: en.interruptMock }));
    expect(screen.getByRole("button", { name: en.recoverMock })).toBeEnabled();
    expect(screen.getByRole("textbox", { name: en.deckAria })).toHaveAttribute("readonly");
    expect(screen.getByLabelText(en.projectName)).toBeDisabled();
    act(() => { vi.advanceTimersByTime(5000); });
    expect(screen.getAllByText(en.interrupted).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: en.recoverMock }));
    fireEvent.click(screen.getByRole("button", { name: en.cancelMock }));
    act(() => { vi.advanceTimersByTime(5000); });
    expect(screen.getAllByText(en.cancelled).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: en.recoverMock })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: en.deckAria })).not.toHaveAttribute("readonly");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("selects regions, constrains zoom and keyboard pan, and keeps Korean controls available", async () => {
    const user = userEvent.setup(); render(<App />);
    await user.click(screen.getByRole("button", { name: en.device }));
    await user.selectOptions(screen.getByLabelText(en.selectRegion), "gate");
    expect(document.querySelector(".device-domain-lines")).toHaveAttribute("data-selection", "gate");
    const svg = screen.getByRole("img", { name: en.deviceAria });
    const region = screen.getByRole("region", { name: en.crossSection });
    for (let count = 0; count < 8; count++) fireEvent.click(screen.getByRole("button", { name: en.zoomIn }));
    expect(screen.getByRole("button", { name: en.zoomIn })).toBeDisabled();
    fireEvent.keyDown(region, { key: "ArrowRight" });
    const values = svg.getAttribute("viewBox")!.split(" ").map(Number);
    expect(values[0]).toBeGreaterThan(300); expect(values[0] + values[2]).toBeLessThanOrEqual(800);
    fireEvent.keyDown(region, { key: "Home" });
    expect(svg).toHaveAttribute("viewBox", "0 0 800 440");
    expect(screen.getByRole("button", { name: en.zoomOut })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "한국어" }));
    expect(screen.getByLabelText(ko.selectRegion)).toHaveValue("gate");
    expect(screen.getByRole("button", { name: ko.panLeft })).toHaveAccessibleName(ko.panLeft);
  });

  it("selects a clicked region even when pointer capture retargets pointer-up, and drags the zoomed view", () => {
    vi.stubGlobal("PointerEvent", MouseEvent);
    render(<App />); fireEvent.click(screen.getByRole("button", { name: en.device }));
    const svg = screen.getByRole("img", { name: en.deviceAria });
    vi.spyOn(svg, "getBoundingClientRect").mockReturnValue({ x: 0, y: 0, left: 0, top: 0, right: 800, bottom: 440, width: 800, height: 440, toJSON: () => ({}) });
    fireEvent.pointerDown(svg.querySelector('[data-region="source"]')!, { button: 0, clientX: 190, clientY: 220 });
    fireEvent.pointerUp(svg, { button: 0, clientX: 190, clientY: 220 });
    expect(screen.getByLabelText(en.selectRegion)).toHaveValue("source");
    fireEvent.click(screen.getByRole("button", { name: en.zoomIn }));
    const before = svg.getAttribute("viewBox");
    fireEvent.pointerDown(svg, { button: 0, clientX: 400, clientY: 220 });
    fireEvent.pointerMove(svg, { buttons: 1, clientX: 440, clientY: 220 });
    fireEvent.pointerUp(svg, { button: 0, clientX: 440, clientY: 220 });
    expect(svg.getAttribute("viewBox")).not.toBe(before);
  });
});

describe("M4 imported data", () => {
  it.each([false, true])("imports and compares same-unit results without network access, local=%s", async (local) => {
    const user = userEvent.setup(); render(<App localBootstrap={local ? { token: "A".repeat(43) } : null} />);
    await user.click(screen.getByRole("button", { name: en.compare }));
    await user.upload(resultInput(), resultFile("A"));
    expect(await screen.findByRole("checkbox", { name: "Compare: A" })).toBeChecked();
    await user.upload(resultInput(), resultFile("B", 0.1));
    await user.click(await screen.findByRole("checkbox", { name: "Compare: B" }));
    expect(screen.getByText(en.maxDifference)).toBeVisible();
    expect(screen.getByText(en.noAcceptance)).toBeVisible();
    expect(screen.getAllByText(en.unverifiedImport).length).toBeGreaterThan(1);
    const before = screen.getAllByRole("checkbox").length;
    await user.upload(resultInput(), new File(['{"format":"opentcad-result","verified":true}'], "forged.json", { type: "application/json" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(en.invalidFile);
    expect(screen.getAllByRole("checkbox")).toHaveLength(before);
    await user.click(screen.getByRole("button", { name: en.device }));
    await user.click(screen.getByRole("button", { name: en.compare }));
    expect(screen.getByRole("checkbox", { name: "Compare: A" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "한국어" }));
    expect(screen.getAllByText(ko.unverifiedImport).length).toBeGreaterThan(1);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("reads CSV, rejects incompatible comparison, and removes only selected in-memory data", async () => {
    const user = userEvent.setup(); render(<App />);
    await user.click(screen.getByRole("button", { name: en.compare }));
    await user.upload(resultInput(), new File(["depth_um,concentration_cm-3\n0,1e20\n1,1e15"], "profile.csv", { type: "text/csv" }));
    expect(await screen.findByRole("img", { name: en.importedProfile })).toBeVisible();
    await user.upload(resultInput(), resultFile("Curve"));
    await user.click(await screen.findByRole("checkbox", { name: "Compare: Curve" }));
    expect(screen.getByRole("alert")).toHaveTextContent(en.compareLimit);
    await user.click(screen.getByRole("button", { name: `${en.removeResult}: profile.csv` }));
    expect(screen.queryByRole("checkbox", { name: "Compare: profile.csv" })).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Compare: Curve" })).toBeInTheDocument();
  });

  it("compares structure extents using the same scale and palette", async () => {
    const user = userEvent.setup(); render(<App />);
    await user.click(screen.getByRole("button", { name: en.compare }));
    for (const [name, width] of [["Small", 1], ["Large", 2]] as const) {
      const data = { format: "opentcad-result", schemaVersion: 1, kind: "structure", name, source: "external", unit: "um", width, height: 1,
        regions: [{ id: "body", material: "silicon", x: 0, y: 0, width, height: 1 }] };
      await user.upload(resultInput(), new File([JSON.stringify(data)], `${name}.json`, { type: "application/json" }));
      await screen.findByRole("checkbox", { name: `Compare: ${name}` });
    }
    await user.click(screen.getByRole("checkbox", { name: "Compare: Large" }));
    const small = screen.getByRole("img", { name: `${en.importedStructure}: Small` });
    const large = screen.getByRole("img", { name: `${en.importedStructure}: Large` });
    expect(Number(small.querySelector("rect")!.getAttribute("width")) * 2).toBe(Number(large.querySelector("rect")!.getAttribute("width")));
    expect(small.querySelectorAll("rect")[1]).toHaveAttribute("fill", large.querySelectorAll("rect")[1].getAttribute("fill"));
  });

  it("enforces the eight-file workspace limit", () => {
    const records: ImportedResult[] = Array.from({ length: 8 }, (_, index) => ({ id: String(index), filename: "file.csv", sha256: null, verified: false,
      data: { format: "opentcad-result", schemaVersion: 1, kind: "iv", name: `File ${index}`, source: "external", xUnit: "V", yUnit: "mA/um", points: [[0, 0], [1, 1]] } }));
    render(<ResultsWorkbench records={records} onChange={() => {}} text={(key) => en[key]} />);
    expect(resultInput()).toBeDisabled();
    expect(screen.getByText(en.resultLimit)).toBeVisible();
    expect(within(screen.getByRole("group", { name: en.compareSelection })).getAllByRole("checkbox")).toHaveLength(8);
  });
});
