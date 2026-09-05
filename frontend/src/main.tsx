import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { consumeLocalBootstrap } from "./local-service";
import "./App.css";
import { consumeExperiment } from "./mvp/solver-client";

const root = document.getElementById("root");
const localBootstrap = consumeLocalBootstrap();
const experimentToken = consumeExperiment();

if (!root) {
  throw new Error("OpenTCAD root element is missing.");
}

createRoot(root).render(
  <StrictMode>
    <App localBootstrap={localBootstrap} experimentToken={experimentToken} />
  </StrictMode>,
);
