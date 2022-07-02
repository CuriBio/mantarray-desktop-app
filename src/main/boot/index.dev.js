/* eslint-disable */
import { app } from "electron";
import installExtension, { VUEJS_DEVTOOLS } from "electron-devtools-installer";
process.env.ELECTRON_DISABLE_SECURITY_WARNINGS = "true";

app.once("browser-window-created", (_, browserWindow) => {
  browserWindow.webContents.once("did-frame-finish-load", () => {
    browserWindow.webContents.openDevTools();
  });
});

app.on("ready", () => installExtension(VUEJS_DEVTOOLS));

// Require `main` process to boot app
require("../index");
