const { app, ipcMain } = require("electron");

// Tanner (1/27/22): before doing anything else, make sure no other instance of the app is open
// based on https://www.electronjs.org/docs/v14-x-y/api/app#apprequestsingleinstancelock
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  // Exit app immediately if another instance is open
  app.exit();
}

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
const barcode_store = main_utils.create_barcode_store();

log.transports.file.resolvePath = () => {
  const filename = main_utils.FILENAME_PREFIX + "_main.txt";

  return path.join(path.dirname(store.path), "logs_flask", main_utils.FILENAME_PREFIX, filename);
};

// set to UTC, not local time
process.env.TZ = "UTC";
console.log = log.log;
console.error = log.error;
console.log("Electron store at: '" + main_utils.redact_username_from_logs(store.path) + "'"); // allow-log
console.log("Barcode store at: '" + main_utils.redact_username_from_logs(barcode_store.path) + "'"); // allow-log

global.__resources = undefined; // eslint-disable-line no-underscore-dangle
// eslint-disable-next-line no-undef
if (__resources === undefined) console.error("[Main-process]: Resources path is undefined");

let win_handler = null;

/**
 * Python Flask
 */
const flask_port = 4567;
const PY_DIST_FOLDER = path.join("dist-python", "mantarray-flask"); // python distributable folder
const PY_EXE = "mantarray-flask"; // the name of the main module

// When booting up (3/27/20), __dirname is equal to: win-unpacked\resources\app\dist\main
const path_to_py_dist_folder = path.join(__dirname, "..", "..", "..", "..", PY_DIST_FOLDER);
const isRunningInBundle = () => {
  console.log("Current dirname: " + main_utils.redact_username_from_logs(__dirname)); // allow-log
  console.log(
    // allow-log
    "To determine if running in bundle, checking the path " +
      main_utils.redact_username_from_logs(path_to_py_dist_folder)
  );
  return fs.existsSync(path_to_py_dist_folder);
};

let wait_for_subprocess_to_complete = null;

const start_python_subprocess = () => {
  console.log("About to generate command line arguments to use when booting up server"); // allow-log
  const python_cmd_line_args = generate_flask_command_line_args(store, barcode_store);
  if (process.argv.includes("--log-level-debug")) python_cmd_line_args.push("--log-level-debug");
  if (process.platform !== "win32") {
    // presumably running in a unix dev or CI environment
    if (!ci.isCI) {
      // don't do this in CI environment, only locally
      python_cmd_line_args.push("--skip-software-version-verification"); // TODO (Eli 3/12/21): use the `yargs` package to accept this as a command line argument to the Electron app so that it can be passed appropriately and with more control than everytime the python source code is run (which is based on the assumption that anytime source code is tested it's running locally in a dev environment and the bit file isn't available)
    }
  }

  const redacted_args = python_cmd_line_args.map((a, i) =>
    i == 0 ? main_utils.redact_username_from_logs(a) : a
  );

  console.log("sending command line args: " + redacted_args); // allow-log
  if (isRunningInBundle()) {
    const script = path.join(path_to_py_dist_folder, PY_EXE);
    console.log(
      // allow-log
      "Launching compiled Python EXE at path: " + main_utils.redact_username_from_logs(script)
    );
    const python_subprocess = require("child_process").execFile(script, python_cmd_line_args);

    wait_for_subprocess_to_complete = new Promise((resolve) => {
      python_subprocess.on("error", (error) => {
        console.log(`Subprocess error: ${error}`);
      });

      python_subprocess.on("exit", (code, signal) => {
        console.log(`Subprocess exiting. Code: ${code}, Termination Signal: ${signal}`);
      });

      python_subprocess.on("close", (code, signal) => {
        console.log(`Subprocess closing. Code: ${code}, Termination Signal: ${signal}`);
        // Tanner (9/19/23): close event fires after the child process is entirely terminated and cleaned up, so resolve promise here and not in exit event
        resolve();
      });
    });
  } else {
    const PythonShell = require("python-shell").PythonShell; // Eli (4/15/20) experienced odd error where the compiled exe was not able to load package python-shell...but since it's only actually required in development, just moving it to here
    if (!store.get("beta_2_mode")) python_cmd_line_args.push("--no-load-firmware");

    console.log("sending command line args: " + redacted_args); // allow-log
    const options = {
      mode: "text",
      pythonPath: process.platform === "win32" ? "python" : "python3",
      // pythonOptions: ['-u'], // get print results in real-time
      scriptPath: path.join("..", "controller", "src"),
      args: python_cmd_line_args,
    };
    const py_file_name = "entrypoint.py";
    const redacted_options = { ...options, args: redacted_args };
    console.log(
      // allow-log
      "Launching Python interpreter to run script '" +
        py_file_name +
        "' with options: " +
        JSON.stringify(redacted_options)
    );
    const python_shell = new PythonShell(py_file_name, options);

    wait_for_subprocess_to_complete = new Promise((resolve) => {
      python_shell.on("close", () => {
        console.log("Python shell closed");
        resolve();
      });
    });
  }
};

const boot_up_flask = function () {
  // start the flask server
  start_python_subprocess();
};

// start the Flask server
boot_up_flask();

const CLOUD_ENDPOINT_USER_OPTION = "REPLACETHISWITHENDPOINTDURINGBUILD";
const CLOUD_ENDPOINT_VALID_OPTIONS = { test: "curibio-test", modl: "curibio-modl", prod: "curibio" };
const CLOUD_DOMAIN = CLOUD_ENDPOINT_VALID_OPTIONS[CLOUD_ENDPOINT_USER_OPTION] || "curibio-test";
// const CLOUD_API_ENDPOINT = `apiv2.${CLOUD_DOMAIN}.com`;
const CLOUD_PULSE3D_ENDPOINT = `pulse3d.${CLOUD_DOMAIN}.com`;

ipcMain.once("pulse3d_versions_request", (event) => {
  axios
    .get(`https://${CLOUD_PULSE3D_ENDPOINT}/versions`)
    .then((response) => {
      const version_info = response.data;
      console.log(`Found pulse3d versions: ${version_info.map(({ version }) => version)}`); // allow-log
      event.reply("pulse3d_versions_response", version_info);
    })
    .catch((response) => {
      console.log(
        // allow-log
        `Error getting pulse3d versions: ${response.status} ${response.statusText}`
      );
      event.reply("pulse3d_versions_response", null);
    });
});

// save customer id after it's verified by /users/login
ipcMain.handle("save_account_info", (_, { customer_id, username }) => {
  store.set("customer_id", customer_id);
  const stored_usernames = store.get("usernames");

  // save username if not already present in stored list of users
  if (!stored_usernames.includes(username)) {
    stored_usernames.push(username);
    store.set("usernames", stored_usernames);
  }

  // return response containing updated customer and usernames to store in Vuex
  return { customer_id, usernames: stored_usernames };
});

ipcMain.on("set_sw_update_auto_install", (e, enable_auto_install) => {
  e.reply("set_sw_update_auto_install", 200);

  const action = enable_auto_install ? "Enabling" : "Disabling";
  console.log(action + " automatic installation of SW updates after shutdown"); // allow-log
  autoUpdater.autoInstallOnAppQuit = enable_auto_install;
});

ipcMain.once("sw_version_request", (event) => {
  event.reply("sw_version_response", get_current_app_version());
});

ipcMain.once("close_app_from_error", (_) => {
  console.log("User acknowledged error and initiated shutdown");
  exit_app_clean();
});

const post_latest_software_version = (version) => {
  let awaiting_response = false;
  const post_interval_id = setInterval(() => {
    if (!awaiting_response) {
      awaiting_response = true;
      axios
        .post(`http://localhost:${flask_port}/latest_software_version?version=${version}`)
        .then((response) => {
          console.log(`/latest_software_version response: ${response.status} ${response.statusText}`); // allow-log;
          if (response.status === 200) clearInterval(post_interval_id);
          awaiting_response = false;
        })
        .catch((response) => {
          awaiting_response = false;
        });
    }
  }, 1000);
};

let sw_update_available = false;

const set_up_auto_updater = () => {
  autoUpdater.autoInstallOnAppQuit = false;

  autoUpdater.forceDevUpdateConfig = true;

  // set up handler for the event in which an update is found
  autoUpdater.once("update-available", (update_info) => {
    const new_version = update_info.version;
    sw_update_available = true;
    console.log("update-available " + new_version); // allow-log
    post_latest_software_version(new_version);
    // remove listeners for update-not-available since this event occured instead
    autoUpdater.removeAllListeners("update-not-available");
  });

  // set up handler for the event in which an update is not found
  autoUpdater.once("update-not-available", () => {
    const current_version = get_current_app_version();
    console.log("update-not-available " + current_version); // allow-log
    post_latest_software_version(current_version);
    // remove listeners for update-available since this event occured instead
    autoUpdater.removeAllListeners("update-available");
  });

  // Check for updates. Will also automatically download the update as long as autoUpdater.autoDownload is true
  autoUpdater.checkForUpdates().catch((response) => {
    console.log("Error while checking for updates: " + JSON.stringify(response)); // allow-log
    const current_version = get_current_app_version();
    post_latest_software_version(current_version);
  });
};

app.on("ready", () => {
  if (!process.env.SPECTRON) {
    // disable on e2e test environment
    if (features.autoupdate) {
      set_up_auto_updater();
    } else {
      console.log("Autoupdate feature disabled"); // allow-log
      const current_version = get_current_app_version();
      post_latest_software_version(current_version);
    }
  }
});

// based on https://www.electronjs.org/docs/v14-x-y/api/app#apprequestsingleinstancelock
app.on("second-instance", (event, command_line, working_directory) => {
  console.log("Prevented second instance from opening"); // allow-log
  if (win_handler && win_handler.browserWindow) {
    if (win_handler.browserWindow.isMinimized()) win_handler.browserWindow.restore();
    win_handler.browserWindow.focus();
  }
});

// This is another place to handle events after all windows are closed
app.once("will-quit", function (e) {
  // This is a good place to add tests ensuring the app is still
  // responsive and all windows are closed.
  console.log("will-quit event being handled"); // allow-log

  // Tanner (9/1/21): Need to prevent (default) app termination, wait for /shutdown response which confirms
  // that the backend is completely shutdown, then call app.exit() which terminates app immediately
  e.preventDefault();

  // Tanner (9/1/21): Need to prevent (default) app termination, wait for /shutdown response which confirms
  // that the backend is completely shutdown, then call app.exit() which terminates app immediately
  axios
    .get(`http://localhost:${flask_port}/shutdown?called_through_app_will_quit=true`)
    .then((response) => {
      console.log(`Flask shutdown response: ${response.status} ${response.statusText}`); // allow-log
      quit_app();
    })
    .catch((response) => {
      console.log(
        // allow-log
        `Error calling Flask shutdown from Electron main process: ${response.status} ${response.statusText}`
      );
      quit_app();
    });
});

const quit_app = () => {
  const auto_install_str = autoUpdater.autoInstallOnAppQuit ? "enabled" : "disabled";
  console.log(
    // allow-log
    "Automatic installation of SW updates after shutdown is " + auto_install_str
  );

  if (autoUpdater.autoInstallOnAppQuit && sw_update_available) {
    app.once("quit", () => {
      exit_app_clean();
    });

    const run_updater_silently = false;
    const run_app_after_install = true;
    autoUpdater.quitAndInstall(run_updater_silently, run_app_after_install);
  } else {
    exit_app_clean();
  }
};

const exit_app_clean = () => {
  if (wait_for_subprocess_to_complete === null) {
    app.exit();
  }

  const wait_for_subprocess_to_complete_with_timeout = new Promise((resolve) => {
    wait_for_subprocess_to_complete.then(() => resolve());
    setTimeout(() => {
      console.log("Backend not closed after timeout"); // allow-log
      resolve();
    }, 8000);
  });
  wait_for_subprocess_to_complete_with_timeout.then(() => {
    console.log("App exiting"); // allow-log
    app.exit();
  });
};

if (gotTheLock) {
  // Extra check to make sure only one window is opened
  win_handler = require("./mainWindow").default;
}
