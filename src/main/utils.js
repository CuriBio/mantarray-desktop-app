const path = require("path");
const url_safe_base64 = require("urlsafe-base64");
import ElectronStore from "./electron_store.js";
const yaml = require("js-yaml");

const now = new Date();
const utc_month = (now.getUTCMonth() + 1).toString().padStart(2, "0"); // Eli (3/29/21) for some reason getUTCMonth returns a zero-based number, while everything else is a month, so adjusting here

const FILENAME_PREFIX = `mantarray_log__${now.getUTCFullYear()}_${utc_month}_${now
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
const get_current_app_version = function () {
  // Eli (3/30/21): Do NOT use `process.env.npm_package_version` to try and do this. It works in CI using the test runner, but does not actually work when running on a standalone machine--it just evaluates to undefined.
  // adapted from https://github.com/electron/electron/issues/7085
  if (process.env.NODE_ENV !== "production") {
    return require("../../package.json").version;
  }
  return require("electron").app.getVersion();
};

/**
 * Creates an ElectronStore. This is a wrapper function to help optionally define file paths for easier testing
 *
 * @param {string} file_path - where to create the store (this will default to somewhere in the User folder if left undefined)
 * @param {string} file_name - what to use as the file name
 *
 * @return {Object} the ElectronStore object
 */
const create_store = function ({ file_path = undefined, file_name = "mantarray_controller_config" } = {}) {
  const store = new ElectronStore({
    cwd: file_path,
    name: file_name,
    fileExtension: "yaml",
    serialize: yaml.dump,
    deserialize: yaml.load,
    defaults: {
      customer_id: null,
      usernames: [],
      beta_2_mode: true,
    },
  });
  return store;
};

const redact_username_from_logs = (dir_path) => {
  const username = dir_path.includes("\\") ? dir_path.split("\\")[2] : dir_path.split("/")[2];
  return dir_path.replace(username, "****");
};

const get_flask_logs_full_path = function (electron_store) {
  const electron_store_dir = path.dirname(electron_store.path);
  return path.join(electron_store_dir, "logs_flask", FILENAME_PREFIX);
};

/**
 * Generate the command line arguments to pass to the local server as it is initialized. This also creates the necessary directories if they don't exist to hold the log files and recordings...although (Eli 1/15/21) unclear why the server doesn't do that itself...
 *
 * @param {Object} electron_store - the ElectronStore object
 *
 * @return {Array} a list of command line arguments
 */
const generate_flask_command_line_args = function (electron_store) {
  console.log("node env: " + process.env.NODE_ENV); // allow-log

  const electron_store_dir = path.dirname(electron_store.path);
  const flask_logs_full_path = get_flask_logs_full_path(electron_store);

  const args = [];
  args.push("--log-file-dir=" + flask_logs_full_path);
  args.push("--expected-software-version=" + export_functions.get_current_app_version());

  const recording_directory_path = path.join(electron_store_dir, "recordings");
  const time_force_dir_path = path.join(electron_store_dir, "time_force_data");

  const settings_to_supply = {
    log_file_id: FILENAME_PREFIX,
    recording_directory: recording_directory_path,
    mag_analysis_output_dir: time_force_dir_path,
  };

  const settings_to_supply_json_str = JSON.stringify(settings_to_supply);
  const settings_to_supply_buf = Buffer.from(settings_to_supply_json_str, "utf8");
  const settings_to_supply_encoded = url_safe_base64.encode(settings_to_supply_buf);

  if (settings_to_supply_json_str !== "{}") {
    args.push("--initial-base64-settings=" + settings_to_supply_encoded);
  }

  if (electron_store.get("beta_2_mode")) args.push("--beta-2-mode");

  return args;
};

// Eli (1/15/21): making spying/mocking with Jest easier. https://medium.com/@DavideRama/mock-spy-exported-functions-within-a-single-module-in-jest-cdf2b61af642
const export_functions = {
  get_flask_logs_full_path,
  generate_flask_command_line_args,
  create_store,
  get_current_app_version,
  FILENAME_PREFIX,
  redact_username_from_logs,
};

export default export_functions;
