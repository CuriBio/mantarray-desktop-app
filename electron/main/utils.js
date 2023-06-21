const path = require("path");
import ElectronStore from "./electronStore.js";
const yaml = require("js-yaml");

const now = new Date();
const utcMonth = (now.getUTCMonth() + 1).toString().padStart(2, "0"); // Eli (3/29/21) for some reason getUTCMonth returns a zero-based number, while everything else is a month, so adjusting here

const FILENAME_PREFIX = `stingray_log__${now.getUTCFullYear()}_${utcMonth}_${now
  .getUTCDate()
  .toString()
  .padStart(2, "0")}_${now
  .getUTCHours()
  .toString()
  .padStart(2, "0")}${now
  .getUTCMinutes()
  .toString()
  .padStart(2, "0")}${now.getUTCSeconds().toString().padStart(2, "0")}`;

/**
 * Depending on whether Electron is running, get the application version from package.json or from the Electron process itself
 *
 * @return {string} the semantic version
 */
const getCurrentAppVersion = function () {
  // Eli (3/30/21): Do NOT use `process.env.npmPackageVersion` to try and do this. It works in CI using the test runner, but does not actually work when running on a standalone machine--it just evaluates to undefined.
  // adapted from https://github.com/electron/electron/issues/7085
  if (process.env.NODE_ENV !== "production") {
    return require("../package.json").version;
  }
  return require("electron").app.getVersion();
};

/**
 * Creates an ElectronStore. This is a wrapper function to help optionally define file paths for easier testing
 *
 * @param {string} filePath - where to create the store (this will default to somewhere in the User folder if left undefined)
 * @param {string} fileName - what to use as the file name
 *
 * @return {Object} the ElectronStore object
 */
const createStore = function ({ filePath = undefined, fileName = "stingray_controller_config" } = {}) {
  const store = new ElectronStore({
    cwd: filePath,
    name: fileName,
    fileExtension: "yaml",
    serialize: yaml.dump,
    deserialize: yaml.load,
    defaults: {
      customer_id: null,
      usernames: [],
    },
  });
  return store;
};

const redactUsernameFromLogs = (dirPath) => {
  const username = dirPath.includes("\\") ? dirPath.split("\\")[2] : dirPath.split("/")[2];
  return dirPath.replace(username, "****");
};

const getLogSubdir = () => {
  return path.join("stingray_logs", FILENAME_PREFIX);
};

const getLogDir = (electronStore) => {
  return path.join(path.dirname(electronStore.path), getLogSubdir());
};

/**
 * Generate the command line arguments to pass to the local server as it is initialized. This also creates the necessary directories if they don't exist to hold the log files and recordings...although (Eli 1/15/21) unclear why the server doesn't do that itself...
 *
 * @param {Object} electronStore - the ElectronStore object
 *
 * @return {Array} a list of command line arguments
 */
const generateFlaskCommandLineArgs = function (electronStore) {
  console.log("node env: " + process.env.NODE_ENV); // allow-log
  const flaskLogsFullPath = getLogDir(electronStore);

  const args = [];
  args.push("--base-directory=" + path.dirname(electronStore.path));
  args.push("--log-directory=" + flaskLogsFullPath);
  args.push("--expected-software-version=" + exportFunctions.getCurrentAppVersion());

  return args;
};

// Eli (1/15/21): making spying/mocking with Jest easier. https://medium.com/@DavideRama/mock-spy-exported-functions-within-a-single-module-in-jest-cdf2b61af642
const exportFunctions = {
  getLogDir,
  generateFlaskCommandLineArgs,
  createStore,
  getCurrentAppVersion,
  FILENAME_PREFIX,
  redactUsernameFromLogs,
};

export default exportFunctions;
