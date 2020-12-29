const path = require("path");
const fs = require("fs");
const mkdirp = require("mkdirp");
const url_safe_base64 = require("urlsafe-base64");
import ElectronStore from "./electron_store.js";
const yaml = require("js-yaml");

export function create_store({
  file_path = undefined,
  file_name = "mantarray_controller_config",
} = {}) {
  let store = new ElectronStore({
    cwd: file_path,
    name: file_name,
    fileExtension: "yaml",
    serialize: yaml.safeDump,
    deserialize: yaml.safeLoad,
    defaults: {
      customer_account_ids: [],
      active_customer_account_index: 0,
      active_user_account_index: 0,
    },
  });
  return store;
}

export function generate_flask_command_line_args(electron_store) {
  const electron_store_dir = path.dirname(electron_store.path);
  let args = [];
  const flask_logs_subfolder = "logs_flask";
  const flask_logs_full_path = path.join(
    electron_store_dir,
    flask_logs_subfolder
  );
  // Eli (7/15/20): Having quotation marks around the path does not appear to be necessary even with spaces in the path, since it's being passed programatically and not directly through the shell
  args.push("--log-file-dir=" + flask_logs_full_path + "");
  const recording_directory_path = path.join(electron_store_dir, "recordings");
  mkdirp.sync(flask_logs_full_path);
  mkdirp.sync(recording_directory_path);

  let settings_to_supply = { recording_directory: recording_directory_path };

  let customer_account_ids = electron_store.get("customer_account_ids");
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
}
