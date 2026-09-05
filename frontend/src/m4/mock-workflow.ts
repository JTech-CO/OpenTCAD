export type MockPhase = "idle" | "running" | "complete" | "cancelled" | "interrupted";
export interface MockEvent { phase: MockPhase; step: number }
export interface MockRun extends MockEvent { generation: number; history: MockEvent[] }
export type MockAction = { type: "start" | "cancel" | "interrupt" | "recover" | "reset" } | { type: "tick"; generation: number };
export const initialMockRun: MockRun = { phase: "idle", step: 0, generation: 0, history: [] };
export function mockReducer(state: MockRun, action: MockAction): MockRun {
  let phase = state.phase, step = state.step, generation = state.generation;
  switch (action.type) {
    case "start":
      if (phase === "running" || phase === "interrupted") return state;
      phase = "running"; step = 0; generation++; break;
    case "tick":
      if (phase !== "running" || action.generation !== generation) return state;
      if (step === 4) phase = "complete"; else step++;
      break;
    case "cancel":
      if (phase !== "running" && phase !== "interrupted") return state;
      phase = "cancelled"; generation++; break;
    case "interrupt":
      if (phase !== "running") return state;
      phase = "interrupted"; generation++; break;
    case "recover":
      if (phase !== "interrupted") return state;
      phase = "running"; generation++; break;
    case "reset":
      if (phase === "running" || phase === "interrupted") return state;
      return { ...initialMockRun, generation: generation + 1 };
  }
  return { phase, step, generation, history: [...state.history, { phase, step }].slice(-20) };
}
