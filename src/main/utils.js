const path = require("path");
const mkdirp = require("mkdirp");
const url_safe_base64 = require("urlsafe-base64");
import ElectronStore from "./electron_store.js";
const yaml = require("js-yaml");

/**
 * Depending on whether Electron is running, get the application version from package.json or from the Electron process itself
 *
 * @return {string} the semantic version
 */
const get_current_app_version = function () {
  return "0.4.1";
  // Eli (1/15/21) - can't figure out how to get it working dynamically
  // try {
  //   const {electron_app} = require("electron").remote;
  // }
  // catch (err) {
  //   if(err instanceof TypeError){
  //       // Electron is not actually running, so get the version from package.json
  //       console.log('Attempting to read the version from package.json') // allow-log
  //       const path_to_package_json=path.join(__dirname,'..','..','package.json')
  //       const package_info=require(path_to_package_json)
  //       return package_info.version
  //   }
  //   else {
  //     console.log( // allow-log
  //       'Something other than TypeError detected when trying to require electron.remote: ' + err)
  //     throw err
  //   }
  // }
  // return electron_app.getVersion()
};

/**
 * Creates an ElectronStore. This is a wrapper function to help optionally define file paths for easier testing
 *
 * @param {string} file_path - where to create the store (this will default to somewhere in the User folder if left undefined)
 * @param {string} file_name - what to use as the file name
 *
 * @return {Object} the ElectronStore object
 */
const create_store = function ({
  file_path = undefined,
  file_name = "mantarray_controller_config",
} = {}) {
  const store = new ElectronStore({
    cwd: file_path,
    name: file_name,
    fileExtension: "yaml",
    serialize: yaml.dump,
    deserialize: yaml.load,
    defaults: {
      customer_account_ids: [],
      active_customer_account_index: 0,
      active_user_account_index: 0,
    },
  });
  return store;
};

/**
 * Generate the command line arguments to pass to the local server as it is initialized. This also creates the necessary directories if they don't exist to hold the log files and recordings...although (Eli 1/15/21) unclear why the server doesn't do that itself...
 *
 * @param {Object} electron_store - the ElectronStore object
 *
 * @return {Array} a list of command line arguments
 */
const generate_flask_command_line_args = function (electron_store) {
  const electron_store_dir = path.dirname(electron_store.path);
  const args = [];
  const flask_logs_subfolder = "logs_flask";
  const flask_logs_full_path = path.join(
    electron_store_dir,
    flask_logs_subfolder
  );
  // Eli (7/15/20): Having quotation marks around the path does not appear to be necessary even with spaces in the path, since it's being passed programatically and not directly through the shell
  args.push("--log-file-dir=" + flask_logs_full_path + "");
  args.push(
    "--expected-software-version=" + export_functions.get_current_app_version()
  );
  const recording_directory_path = path.join(electron_store_dir, "recordings");
  mkdirp.sync(flask_logs_full_path);
  mkdirp.sync(recording_directory_path);

  const settings_to_supply = { recording_directory: recording_directory_path };

  const customer_account_ids = electron_store.get("customer_account_ids");
  if (customer_account_ids.length > 0) {
    const active_customer_account = customer_account_ids[0];
    settings_to_supply.customer_account_uuid = active_customer_account.uuid;
    settings_to_supply.user_account_uuid =
      active_customer_account.user_account_ids[0].uuid;
  }

  const settings_to_supply_json_str = JSON.stringify(settings_to_supply);
  const settings_to_supply_buf = Buffer.from(
    settings_to_supply_json_str,
    "utf8"
  );
  const settings_to_supply_encoded = url_safe_base64.encode(
    settings_to_supply_buf
  );

  if (settings_to_supply_json_str !== "{}") {
    args.push("--initial-base64-settings=" + settings_to_supply_encoded);
  }

  return args;
};

// Eli (1/15/21): making spying/mocking with Jest easier. https://medium.com/@DavideRama/mock-spy-exported-functions-within-a-single-module-in-jest-cdf2b61af642
const export_functions = {
  generate_flask_command_line_args,
  create_store,
  get_current_app_version,
};
export default export_functions;
