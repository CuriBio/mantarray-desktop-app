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

import mainUtils from "./utils.js"; // Eli (1/15/21): helping to be able to spy on functions within utils. https://stackoverflow.com/questions/49457451/jest-spyon-a-function-not-class-or-object-type
const createStore = mainUtils.createStore;
const generateFlaskCommandLineArgs = mainUtils.generateFlaskCommandLineArgs;
const getCurrentAppVersion = mainUtils.getCurrentAppVersion;

const store = createStore();

log.transports.file.resolvePath = () => {
  const filename = mainUtils.FILENAME_PREFIX + "_main.txt";

  return path.join(path.dirname(store.path), "stingray_logs", mainUtils.FILENAME_PREFIX, filename);
};

// set to UTC, not local time
process.env.TZ = "UTC";
console.log = log.log;
console.error = log.error;
console.log("Electron store at: '" + mainUtils.redactUsernameFromLogs(store.path) + "'"); // allow-log

global.__resources = undefined; // eslint-disable-line no-underscore-dangle
// eslint-disable-next-line no-undef
if (__resources === undefined) console.error("[Main-process]: Resources path is undefined");

let winHandler = null;

/**
 * Python Subprocess
 */
const PY_DIST_FOLDER = path.join("dist-python", "instrument-controller"); // python distributable folder
const PY_EXE = "instrument-controller"; // the name of the main module

// When booting up (3/27/20), __dirname is equal to: win-unpacked\resources\app\dist\main
const pathToPyDistFolder = path.join(__dirname, "..", "..", "..", "..", PY_DIST_FOLDER);
const isRunningInBundle = () => {
  console.log("Current dirname: " + mainUtils.redactUsernameFromLogs(__dirname)); // allow-log
  console.log(
    // allow-log
    "To determine if running in bundle, checking the path " +
      mainUtils.redactUsernameFromLogs(pathToPyDistFolder)
  );
  return fs.existsSync(pathToPyDistFolder);
};

let waitForSubprocessToComplete = null;

const startPythonSubprocess = () => {
  console.log("About to generate command line arguments to use when booting up server"); // allow-log
  const pythonCmdLineArgs = generateFlaskCommandLineArgs(store);
  if (process.argv.includes("--log-level-debug")) pythonCmdLineArgs.push("--log-level-debug");
  if (process.platform !== "win32") {
    // presumably running in a unix dev or CI environment
    if (!ci.isCI) {
      // don't do this in CI environment, only locally
      pythonCmdLineArgs.push("--skip-software-version-verification");
    }
  }

  const redactedArgs = pythonCmdLineArgs.map((a, i) => (i == 0 ? mainUtils.redactUsernameFromLogs(a) : a));

  console.log("sending command line args: " + redactedArgs); // allow-log
  if (isRunningInBundle()) {
    const script = path.join(pathToPyDistFolder, PY_EXE);
    console.log(
      // allow-log
      "Launching compiled Python EXE at path: " + mainUtils.redactUsernameFromLogs(script)
    );
    const pythonSubprocess = require("child_process").execFile(script, pythonCmdLineArgs);

    waitForSubprocessToComplete = new Promise((resolve) => {
      pythonSubprocess.on("close", (code, signal) =>
        resolve(`Subprocess exit code: ${code}: termination signal ${signal}`)
      );
    });
  } else {
    const PythonShell = require("python-shell").PythonShell; // Eli (4/15/20) experienced odd error where the compiled exe was not able to load package python-shell...but since it's only actually required in development, just moving it to here

    console.log("sending command line args: " + redactedArgs); // allow-log
    const options = {
      mode: "text",
      pythonPath: process.platform === "win32" ? "python" : "python3",
      // pythonOptions: ['-u'], // get print results in real-time
      scriptPath: path.join("..", "controller", "src"),
      args: pythonCmdLineArgs,
    };
    const pyFileName = "entrypoint.py";
    const redactedOptions = { ...options, args: redactedArgs };
    console.log(
      // allow-log
      "Launching Python interpreter to run script '" +
        pyFileName +
        "' with options: " +
        JSON.stringify(redactedOptions)
    );
    const pythonShell = new PythonShell(pyFileName, options);

    waitForSubprocessToComplete = new Promise((resolve) => {
      pythonShell.on("close", () => resolve("Python shell closed"));
    });
  }
};

const bootUpFlask = function () {
  // start the flask server
  startPythonSubprocess();
};

// start the Flask server
bootUpFlask();

const CLOUD_ENDPOINT_USER_OPTION = "REPLACETHISWITHENDPOINTDURINGBUILD";
const CLOUD_ENDPOINT_VALID_OPTIONS = { test: "curibio-test", prod: "curibio" };
const CLOUD_DOMAIN = CLOUD_ENDPOINT_VALID_OPTIONS[CLOUD_ENDPOINT_USER_OPTION] || "curibio-test";
// const CLOUD_API_ENDPOINT = `apiv2.${CLOUD_DOMAIN}.com`;
const CLOUD_PULSE3D_ENDPOINT = `pulse3d.${CLOUD_DOMAIN}.com`;

ipcMain.once("pulse3dVersionsRequest", (event) => {
  axios
    .get(`https://${CLOUD_PULSE3D_ENDPOINT}/versions`)
    .then((response) => {
      const versions = response.data.map(({ version }) => version);
      console.log(`Found pulse3d versions: ${versions}`); // allow-log
      event.reply("pulse3dVersionsResponse", versions);
    })
    .catch((response) => {
      console.log(
        // allow-log
        `Error getting pulse3d versions: ${response.status} ${response.statusText}`
      );
      event.reply("pulse3dVersionsResponse", null);
    });
});

// save customer id after it's verified by /users/login
ipcMain.handle("saveAccountInfoRequest", (_, { customerId, username }) => {
  store.set("customer_id", customerId);
  const storedUsernames = store.get("usernames");

  // save username if not already present in stored list of users
  if (!storedUsernames.includes(username)) {
    storedUsernames.push(username);
    store.set("usernames", storedUsernames);
  }

  // return response containing updated customer and usernames to store in Vuex
  return { customerId, usernames: storedUsernames };
});

ipcMain.on("setSwUpdateAutoInstall", (e, enableAutoInstall) => {
  e.reply("setSwUpdateAutoInstall", 200);

  const action = enableAutoInstall ? "Enabling" : "Disabling";
  console.log(action + " automatic installation of SW updates after shutdown"); // allow-log
  autoUpdater.autoInstallOnAppQuit = enableAutoInstall;
});

ipcMain.once("swVersionRequest", (event) => {
  event.reply("swVersionResponse", getCurrentAppVersion());
});

let setLatestSwVersion;

const waitForLatestSwVersion = new Promise((resolve) => {
  setLatestSwVersion = resolve;
});

ipcMain.once("latestSwVersionRequest", (event) => {
  waitForLatestSwVersion.then((latestVersion) => {
    event.reply("latestSwVersionResponse", latestVersion);
  });
});

let swUpdateAvailable = false;

const setUpAutoUpdater = () => {
  autoUpdater.autoInstallOnAppQuit = false;

  autoUpdater.forceDevUpdateConfig = true;

  // set up handler for the event in which an update is found
  autoUpdater.once("update-available", (updateInfo) => {
    const newVersion = updateInfo.version;
    swUpdateAvailable = true;
    console.log("update-available " + newVersion); // allow-log
    setLatestSwVersion(newVersion);
    // remove listeners for update-not-available since this event occured instead
    autoUpdater.removeAllListeners("update-not-available");
  });

  // set up handler for the event in which an update is not found
  autoUpdater.once("update-not-available", () => {
    const currentVersion = getCurrentAppVersion();
    console.log("update-not-available " + currentVersion); // allow-log
    setLatestSwVersion(currentVersion);
    // remove listeners for update-available since this event occured instead
    autoUpdater.removeAllListeners("update-available");
  });

  // Check for updates. Will also automatically download the update as long as autoUpdater.autoDownload is true
  autoUpdater.checkForUpdates().catch((response) => {
    console.log("Error while checking for updates: " + JSON.stringify(response)); // allow-log
    const currentVersion = getCurrentAppVersion();
    setLatestSwVersion(currentVersion);
  });
};

app.on("ready", () => {
  if (!process.env.SPECTRON) {
    // disable on e2e test environment
    if (features.autoupdate) {
      setUpAutoUpdater();
    } else {
      console.log("Autoupdate feature disabled"); // allow-log
      const currentVersion = getCurrentAppVersion();
      setLatestSwVersion(currentVersion);
    }
  }
});

// based on https://www.electronjs.org/docs/v14-x-y/api/app#apprequestsingleinstancelock
app.on("second-instance", (event, commandLine, workingDirectory) => {
  console.log("Prevented second instance from opening"); // allow-log
  if (winHandler && winHandler.browserWindow) {
    if (winHandler.browserWindow.isMinimized()) winHandler.browserWindow.restore();
    winHandler.browserWindow.focus();
  }
});

// This is another place to handle events after all windows are closed
app.once("will-quit", function (e) {
  console.log("will-quit event being handled"); // allow-log

  // prevent default behavior which is the app immediately closing upon completion of this callback.
  // app exit will be handled manually
  e.preventDefault();

  const autoInstallStr = autoUpdater.autoInstallOnAppQuit ? "enabled" : "disabled";
  console.log(
    // allow-log
    "Automatic installation of SW updates after shutdown is " + autoInstallStr
  );

  if (autoUpdater.autoInstallOnAppQuit && swUpdateAvailable) {
    app.once("quit", () => {
      exitAppClean();
    });

    const runUpdaterSilently = false;
    const runAppAfterInstall = true;
    autoUpdater.quitAndInstall(runUpdaterSilently, runAppAfterInstall);
  } else {
    exitAppClean();
  }
});

const exitAppClean = () => {
  const exit = () => {
    console.log("App exiting"); // allow-log
    app.exit();
  };

  if (waitForSubprocessToComplete === null) {
    console.log("No subprocess being waited on");
    exit();
  }

  const waitForSubprocessToCompleteWithTimeout = new Promise((resolve) => {
    waitForSubprocessToComplete.then((msg) => resolve(msg));
    setTimeout(() => resolve("Controller process not closed after timeout"), 8000);
  });
  waitForSubprocessToCompleteWithTimeout.then((msg) => {
    console.log(msg); // allow-log
    exit();
  });
};

if (gotTheLock) {
  // Extra check to make sure only one window is opened
  winHandler = require("./mainWindow").default;
}
