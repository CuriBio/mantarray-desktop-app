import { app } from "electron";
import electronDebug from "electron-debug";
import fs from "fs";
import path from "path";

// const electron_config_path = path.join(
//   __dirname,
//   "..",
//   "..",
//   ".electron-nuxt",
//   "config"
// );

// const main_window_path = path.resolve("./mainWindow");

process.env.ELECTRON_DISABLE_SECURITY_WARNINGS = "true";

electronDebug({
  showDevTools: true,
  devToolsMode: "top",
});

// work around https://github.com/MarshallOfSound/electron-devtools-installer/issues/122
// which seems to be a result of https://github.com/electron/electron/issues/19468
if (process.platform === "win32") {
  const appUserDataPath = app.getPath("userData");
  const devToolsExtensionsPath = path.join(appUserDataPath, "DevTools Extensions");
  try {
    fs.unlinkSync(devToolsExtensionsPath);
  } catch (_) {
    // don't complain if the file doesn't exist
  }
}

app.on("ready", () => {
  // Menu.setApplicationMenu(menu);
});

// Require `main` process to boot app
require("../index");
