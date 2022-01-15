/* globals INCLUDE_RESOURCES_PATH */
const { app, ipcMain } = require("electron");
const { autoUpdater } = require("electron-updater");
const log = require("electron-log");
const path = require("path");
const features = require("./features.json");

const ci = require("ci-info");
const fs = require("fs");
const axios = require("axios");

import main_utils from "./utils.js"; // Eli (1/15/21): helping to be able to spy on functions within utils. https://stackoverflow.com/questions/49457451/jest-spyon-a-function-not-class-or-object-type
const create_store = main_utils.create_store;
const generate_flask_command_line_args = main_utils.generate_flask_command_line_args;
const get_current_app_version = main_utils.get_current_app_version;

const store = create_store();

log.transports.file.resolvePath = () => {
  const filename = main_utils.filename_prefix + "_main.txt";

  return path.join(path.dirname(store.path), "logs_flask", main_utils.filename_prefix, filename);
};
console.log = log.log;
console.error = log.error;
console.log(
  "Electron store at: '" +
  main_utils.redact_username_from_logs(store.path) +
  "'"
);

global.__resources = undefined; // eslint-disable-line no-underscore-dangle
// noinspection BadExpressionStatementJS
INCLUDE_RESOURCES_PATH; // eslint-disable-line no-unused-expressions
// Eli (1/15/21): this code is straight from the template, so unclear what would happen if it was changed and how `__resources` may or may not be being injected into this somehow
// eslint-disable-next-line no-undef
if (__resources === undefined) console.error("[Main-process]: Resources path is undefined");

/**
 * Python Flask
 */
const flask_port = 4567;
const PY_DIST_FOLDER = path.join("dist-python", "mantarray-flask"); // python distributable folder
const PY_SRC_FOLDER = "src"; // path to the python source
const PY_MODULE = "entrypoint.py"; // the name of the main module
const PY_EXE = "mantarray-flask"; // the name of the main module

// When booting up (3/27/20), __dirname is equal to: win-unpacked\resources\app\dist\main
const path_to_py_dist_folder = path.join(__dirname, "..", "..", "..", "..", PY_DIST_FOLDER);
const isRunningInBundle = () => {
  console.log(
    "Current dirname: " + main_utils.redact_username_from_logs(__dirname)
  ); // allow-log
  console.log(
    // allow-log
    "To determine if running in bundle, checking the path " +
    main_utils.redact_username_from_logs(path_to_py_dist_folder)
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
  console.log("About to generate command line arguments to use when booting up server"); // allow-log
  const command_line_args = generate_flask_command_line_args(store);
  if (process.platform !== "win32") {
    // presumably running in a linux dev or CI environment
    if (!ci.isCI) {
      // don't do this in CI environment, only locally
      command_line_args.push("--skip-software-version-verification"); // TODO (Eli 3/12/21): use the `yargs` package to accept this as a command line argument to the Electron app so that it can be passed appropriately and with more control than everytime the python source code is run (which is based on the assumption that anytime source code is tested it's running locally in a dev environment and the bit file isn't available)
    }
  }

  const redacted_args = command_line_args.map((a, i) =>
    i == 0 ? main_utils.redact_username_from_logs(a) : a
  );

  console.log("sending command line args: " + redacted_args); // allow-log
  if (isRunningInBundle()) {
    const script = getPythonScriptPath();
    console.log(
      // allow-log
      "Launching compiled Python EXE at path: " +
      main_utils.redact_username_from_logs(script)
    );
    require("child_process").execFile(script, command_line_args);
  } else {
    const PythonShell = require("python-shell").PythonShell; // Eli (4/15/20) experienced odd error where the compiled exe was not able to load package python-shell...but since it's only actually required in development, just moving it to here
    if (!store.get("beta_2_mode")) command_line_args.push("--no-load-firmware");

    console.log("sending command line args: " + redacted_args); // allow-log
    const options = {
      mode: "text",
      pythonPath: process.platform === "win32" ? "python" : "python3",
      // pythonOptions: ['-u'], // get print results in real-time
      scriptPath: "src",
      args: command_line_args,
    };
    const py_file_name = "entrypoint.py";
    const redacted_options = { ...options, args: redacted_args };
    console.log(
      // allow-log
      "Launching Python interpreter to run script '" +
      py_file_name +
      "' with options: " +
      JSON.stringify(options)
    );
    new PythonShell(py_file_name, options);
  }
};

const boot_up_flask = function () {
  // start the flask server
  start_python_subprocess();
};

// start the Flask server
boot_up_flask();

// save customer id after it's verified in the /get_auth aws route
ipcMain.on("save_customer_id", (e, customer_account) => {
  e.reply("save_customer_id", 200);

  const { cust_id, pass_key } = customer_account;
  store.set("customer_account_id", {
    id: cust_id,
    password: pass_key,
  });
});

ipcMain.on("set_sw_update_auto_install", (e, enable_auto_install) => {
  e.reply("save_customer_id", 200);

  const action = enable_auto_install ? "Enabling" : "Disabling";
  console.log(action + " automatic installation of SW updates after shutdown"); // allow-log
  autoUpdater.autoInstallOnAppQuit = enable_auto_install;
});

const set_up_auto_updater = () => {
  autoUpdater.autoInstallOnAppQuit = false;

  // set up handler for the event in which an update is found
  autoUpdater.once("update-available", (update_info) => {
    const new_version = update_info.version;
    console.log("update-available " + new_version); // allow-log
    axios.post(`http://localhost:${flask_port}/latest_software_version?version=${new_version}`);
    // remove listeners for update-not-available since this event occured instead
    autoUpdater.removeAllListeners("update-not-available");
  });

  // TODO make sure offline mode is handled
  // set up handler for the event in which an update is not found
  autoUpdater.once("update-not-available", () => {
    const current_version = get_current_app_version();
    console.log("update-not-available " + current_version); // allow-log
    axios.post(`http://localhost:${flask_port}/latest_software_version?version=${current_version}`);
    // remove listeners for update-available since this event occured instead
    autoUpdater.removeAllListeners("update-available");
  });

  // Check for updates. Will also automatically download the update as long as autoUpdater.autoDownload is true
  autoUpdater.checkForUpdates(); // TODO catch errors on this?
};

app.on("ready", () => {
  if (!process.env.SPECTRON) {
    // disable on e2e test environment
    if (features.autoupdate) {
      set_up_auto_updater();
    } else {
      console.log("Autoupdate feature disabled"); // allow-log
      const current_version = get_current_app_version();
      axios.post(`http://localhost:${flask_port}/latest_software_version?version=${current_version}`);
    }
  }
});

// This is another place to handle events after all windows are closed
app.on("will-quit", function (e) {
  // This is a good place to add tests ensuring the app is still
  // responsive and all windows are closed.
  console.log("will-quit event being handled"); // allow-log

  const auto_install_str = autoUpdater.autoInstallOnAppQuit ? "enabled" : "disabled";
  console.log(
    // allow-log
    "Automatic installation of SW updates after shutdown is " + auto_install_str
  );

  // Tanner (9/1/21): Need to prevent (default) app termination, wait for /shutdown response which confirms
  // that the backend is completely shutdown, then call app.exit() which terminates app immediately
  e.preventDefault();

  // Tanner (9/1/21): Need to prevent (default) app termination, wait for /shutdown response which confirms
  // that the backend is completely shutdown, then call app.exit() which terminates app immediately
  axios
    .get(`http://localhost:${flask_port}/shutdown?called_through_app_will_quit=true`)
    .then((response) => {
      console.log(`Shutdown response: ${response.status} ${response.statusText}`); // allow-log
      app.exit();
    })
    .catch((response) => {
      console.log(
        // allow-log
        `Error calling shutdown from Electron main process: ${response.status} ${response.statusText}`
      );
      app.exit();
    });
});

require("./mainWindow");
