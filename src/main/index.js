/* globals INCLUDE_RESOURCES_PATH */
import { app } from "electron";
const autoUpdater = require("electron-updater");
const log = require("electron-log");
const path = require("path");
const features = require("./features.json");
const now = new Date();
const utc_month = (now.getUTCMonth() + 1).toString().padStart(2, "0"); // Eli (3/29/21) for some reason getUTCMonth returns a zero-based number, while everything else is a month, so adjusting here
const filename_prefix = `mantarray_log__${now.getUTCFullYear()}_${utc_month}_${now
  .getUTCDate()
  .toString()
  .padStart(2, "0")}_${now
  .getUTCHours()
  .toString()
  .padStart(2, "0")}${now
  .getUTCMinutes()
  .toString()
  .padStart(2, "0")}${now.getUTCSeconds().toString().padStart(2, "0")}_`;

log.transports.file.resolvePath = (variables) => {
  let filename;
  switch (process.type) {
    case "renderer":
      filename = filename_prefix + "renderer";
      break;
    case "worker":
      filename = filename_prefix + "worker";
      break;
    default:
      filename = filename_prefix + "main";
  }
  filename = filename + ".txt";
  return path.join(variables.libraryDefaultDir, "..", "logs_flask", filename);
};
console.log = log.log;
console.error = log.error;
/* Eli added */
// import './style.scss'
// import 'typeface-roboto/index.css' // https://medium.com/@daddycat/using-offline-material-icons-and-roboto-font-in-electron-app-f25082447443
// require('typeface-roboto')
/* end Eli added */
const ci = require("ci-info");

const fs = require("fs");
const axios = require("axios");
// const {
//   create_store,
//   generate_flask_command_line_args,
// } = require("./utils.js");
import main_utils from "./utils.js"; // Eli (1/15/21): helping to be able to spy on functions within utils. https://stackoverflow.com/questions/49457451/jest-spyon-a-function-not-class-or-object-type
const create_store = main_utils.create_store;
const generate_flask_command_line_args =
  main_utils.generate_flask_command_line_args;
// const ElectronStore = require("electron-store");
/**
 * Set `__resources` path to resources files in renderer process
 */
global.__resources = undefined; // eslint-disable-line no-underscore-dangle
// noinspection BadExpressionStatementJS
INCLUDE_RESOURCES_PATH; // eslint-disable-line no-unused-expressions
// Eli (1/15/21): this code is straight from the template, so unclear what would happen if it was changed and how `__resources` may or may not be being injected into this somehow
// eslint-disable-next-line no-undef
if (__resources === undefined)
  console.error("[Main-process]: Resources path is undefined");

let store;

/**
 * Python Flask
 */
const flask_port = 4567;
const PY_DIST_FOLDER = path.join("dist-python", "mantarray-flask"); // python distributable folder
const PY_SRC_FOLDER = "src"; // path to the python source
const PY_MODULE = "entrypoint.py"; // the name of the main module
const PY_EXE = "mantarray-flask"; // the name of the main module

// const nodeConsole = require("console");
// const myConsole = new nodeConsole.Console(process.stdout, process.stderr);
// When booting up (3/27/20), __dirname is equal to: win-unpacked\resources\app\dist\main
const path_to_py_dist_folder = path.join(
  __dirname,
  "..",
  "..",
  "..",
  "..",
  PY_DIST_FOLDER
);
const isRunningInBundle = () => {
  console.log("Current dirname: " + __dirname); // allow-log
  console.log(
    // allow-log
    "To determine if running in bundle, checking the path " +
      path_to_py_dist_folder
  );
  return fs.existsSync(path_to_py_dist_folder);
};

const getPythonScriptPath = () => {
  const up_two_dirs = path.resolve(__dirname, "..", ".."); // https://stackoverflow.com/questions/7083045/fs-how-do-i-locate-a-parent-folder
  const bundled_path = path.join(path_to_py_dist_folder, PY_EXE);
  const unbundled_path = path.join(up_two_dirs, PY_SRC_FOLDER, PY_MODULE);
  if (!isRunningInBundle()) {
    return unbundled_path;
  }
  return bundled_path;
};

const start_python_subprocess = () => {
  console.log(
    // allow-log
    "About to generate command line arguments to use when booting up server"
  );
  const command_line_args = generate_flask_command_line_args(store);
  if (process.platform !== "win32") {
    // presumably running in a linux dev or CI environment
    if (!ci.isCI) {
      // don't do this in CI environment, only locally
      command_line_args.push("--skip-software-version-verification"); // TODO (Eli 3/12/21): use the `yargs` package to accept this as a command line argument to the Electron app so that it can be passed appropriately and with more control than everytime the python source code is run (which is based on the assumption that anytime source code is tested it's running locally in a dev environment and the bit file isn't available)
    }
  }

  console.log("sending command line args: " + command_line_args); // allow-log
  if (isRunningInBundle()) {
    const script = getPythonScriptPath();
    console.log(
      // allow-log
      "Launching compiled Python EXE at path: " + script
    );
    // const subpy = require("child_process").execFile(script, command_line_args);
    require("child_process").execFile(script, command_line_args);
  } else {
    const PythonShell = require("python-shell").PythonShell; // Eli (4/15/20) experienced odd error where the compiled exe was not able to load package python-shell...but since it's only actually required in development, just moving it to here
    command_line_args.push("--no-load-firmware"); // TODO (Eli 2/24/21): use the `yargs` package to accept this as a command line argument to the Electron app so that it can be passed appropriately and with more control than everytime the python source code is run (which is based on the assumption that anytime source code is tested it's running locally in a dev environment and the bit file isn't available)
    console.log("sending command line args: " + command_line_args); // allow-log
    const options = {
      mode: "text",
      pythonPath: "python3", // In Cloud9, you need to specify python3 to use the installation inside the virtual environment...just Python defaults to system installation
      // pythonOptions: ['-u'], // get print results in real-time
      scriptPath: "src",
      args: command_line_args,
    };
    const py_file_name = "entrypoint.py";
    console.log(
      // allow-log
      "Launching Python interpreter to run script '" +
        py_file_name +
        "' with options: " +
        JSON.stringify(options)
    );
    // const pyshell = new PythonShell(py_file_name, options);
    new PythonShell(py_file_name, options);
    // PythonShell.run(py_file_name,options)
  }
};

const boot_up_flask = function () {
  // start the flask server
  start_python_subprocess();
};

const init_electron_store = function () {
  store = create_store();
  console.log("Electron store at: '" + store.path + "'"); // allow-log
};

init_electron_store();

// start the Flask server
boot_up_flask();
// Quit when all windows are closed.
app.on("window-all-closed", function () {
  // On macOS it is common for applications and their menu bar
  // to stay active until the user quits explicitly with Cmd + Q
  console.log("window-all-closed event being handled"); // allow-log
  if (process.platform !== "darwin") app.quit();
});
// let win_handler = null;
app.on("ready", () => {
  console.log("ready in index.js");
  if (features.autoupdate) {
    autoUpdater.checkForUpdatesAndNotify();
  } else {
    console.log("Autoupdate feature disabled");
  }
});

// This is another place to handle events after all windows are closed
app.on("will-quit", function () {
  // This is a good place to add tests ensuring the app is still
  // responsive and all windows are closed.
  console.log("will-quit event being handled"); // allow-log
  // mainWindow = null;

  axios.get(
    `http://localhost:${flask_port}/shutdown?called_through_app_will_quit=true`
  );
});

// win_handler = require("./mainWindow");
require("./mainWindow");
