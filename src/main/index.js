/* globals INCLUDE_RESOURCES_PATH */
import { app, Screen } from "electron";

/* Eli added */
// import './style.scss'
// import 'typeface-roboto/index.css' // https://medium.com/@daddycat/using-offline-material-icons-and-roboto-font-in-electron-app-f25082447443
// require('typeface-roboto')
/* end Eli added */

const path = require("path");
const fs = require("fs");
const axios = require("axios");
const {
  create_store,
  generate_flask_command_line_args,
} = require("./utils.js");
const ElectronStore = require("electron-store");
const yaml = require("js-yaml");
const mkdirp = require("mkdirp");
/**
 * Set `__resources` path to resources files in renderer process
 */
global.__resources = undefined; // eslint-disable-line no-underscore-dangle
// noinspection BadExpressionStatementJS
INCLUDE_RESOURCES_PATH; // eslint-disable-line no-unused-expressions
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
const PY_EXE = "mantarray-flask.exe"; // the name of the main module

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
  const command_line_args = generate_flask_command_line_args(store);
  if (isRunningInBundle()) {
    const script = getPythonScriptPath();
    console.log(
      // allow-log
      "Launching compiled Python EXE at path: " +
        script +
        " With command line args: " +
        command_line_args
    );
    const subpy = require("child_process").execFile(script, command_line_args);
  } else {
    const PythonShell = require("python-shell").PythonShell; // Eli (4/15/20) experienced odd error where the compiled exe was not able to load package python-shell...but since it's only actually required in development, just moving it to here
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
    const pyshell = new PythonShell(py_file_name, options);
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
let win_handler = null;
app.on("ready", () => {
  console.log("ready in index.js");
});

// This is another place to handle events after all windows are closed
app.on("will-quit", function () {
  // This is a good place to add tests insuring the app is still
  // responsive and all windows are closed.
  console.log("will-quit event being handled"); // allow-log
  // mainWindow = null;

  axios.get(`http://localhost:${flask_port}/shutdown`);
});

win_handler = require("./mainWindow");
