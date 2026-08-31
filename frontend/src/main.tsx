import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { consumeLocalBootstrap } from "./local-service";
import "./App.css";

const root = document.getElementById("root");
const localBootstrap = consumeLocalBootstrap();

if (!root) {
  throw new Error("OpenTCAD root element is missing.");
}

createRoot(root).render(
  <StrictMode>
    <App localBootstrap={localBootstrap} />
  </StrictMode>,
);
