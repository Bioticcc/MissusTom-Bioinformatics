import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { RunOverlay } from "./components/RunOverlay";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {new URLSearchParams(window.location.search).get("overlay") === "run" ? <RunOverlay /> : <App />}
  </React.StrictMode>,
);
