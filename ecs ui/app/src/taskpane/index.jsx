import * as React from "react";
import { createRoot } from "react-dom/client";
import App from "./components/App";
import { FluentProvider, webLightTheme } from "@fluentui/react-components";

/* global document, Office, module, require */

const title = "Otsuka Add-in";

const rootElement = document.getElementById("container");
const root = rootElement ? createRoot(rootElement) : undefined;

async function checkForUpdate() {
  try {
    const res = await fetch(`/version.json?ts=${Date.now()}`);
    const { version } = await res.json();

    const storedVersion = localStorage.getItem("addin_version");
    console.log("current version: ", version, "storedVersion: ", storedVersion)

    // If version changed → reload once
    if (storedVersion && storedVersion !== version) {
      localStorage.setItem("addin_version", version);
      window.location.reload(true);
      return false; // stop rendering
    }

    // First time load
    if (!storedVersion) {
      localStorage.setItem("addin_version", version);
    }

    return true;
  } catch (err) {
    console.log("Version check skipped");
    return true; // continue rendering if version check fails
  }
}

/* Render application after Office initializes */
Office.onReady(async() => {
  const shouldRender = await checkForUpdate();

  if (!shouldRender) return;
  root?.render(
    <FluentProvider theme={webLightTheme}>
      <App title={title} />
    </FluentProvider>
  );
});

if (module.hot) {
  module.hot.accept("./components/App", () => {
    const NextApp = require("./components/App").default;
    root?.render(NextApp);
  });
}
