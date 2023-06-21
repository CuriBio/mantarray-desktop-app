const path = require("path");

const ELECTRON_ROOT = path.join(__dirname, "..");

const config = {
  ELECTRON_RELAUNCH_CODE: 250, // valid range in unix system: <1,255>
  ELECTRON_INSPECTION_PORT: 5858,
  SERVER_PORT: 9080,
  SERVER_HOST: "http://localhost",

  MAIN_PROCESS_DIR: path.join(ELECTRON_ROOT, "main"),
  RENDERER_PROCESS_DIR: path.join(ELECTRON_ROOT, "renderer"),
  RESOURCES_DIR: path.join(ELECTRON_ROOT, "extraResources"),
  DIST_DIR: path.join(ELECTRON_ROOT, "dist"),

  DISABLE_BABEL_LOADER: false, // experimental
};

module.exports = Object.freeze(config);
