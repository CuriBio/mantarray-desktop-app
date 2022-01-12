const path = require("path");
const fs = require("fs");
const tmp = require("tmp");
tmp.setGracefulCleanup(); // Eli (7/13/20): According to the docs, this is supposed to enforce automatic deletion of the folders at the end of running the process, but it does not appear to be working. Manual cleanup seems to be required.
const url_safe_base64 = require("urlsafe-base64");
// import create_store,generate_flask_command_line_args,get_current_app_version from "@/main/utils.js";
// const {
//   create_store,
//   generate_flask_command_line_args,get_current_app_version
// } = require("@/main/utils.js");

// import default as main_utils from "@/main/utils.js" // Eli (1/15/21): helping to be able to spy on functions within utils. https://stackoverflow.com/questions/49457451/jest-spyon-a-function-not-class-or-object-type
import main_utils from "@/main/utils.js"; // Eli (1/15/21): helping to be able to spy on functions within utils. https://stackoverflow.com/questions/49457451/jest-spyon-a-function-not-class-or-object-type
import { filename_prefix } from "@/main/index.js";
const sinon = require("sinon");
// const sinon_helpers = require("sinon-helpers");

const sandbox = sinon.createSandbox({
  useFakeTimers: false, // Eli (6/14/20): fakeTimers can mess with Jest's builtin timers for timeouts for the tests. If you need to fake things about time, do so carefully, such as with sandbox.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
});

describe("utils.js", () => {
  afterEach(() => {
    jest.restoreAllMocks();
    sandbox.restore();
  });
  describe("Given a temporary directory is available", () => {
    let tmp_dir_name;
    let tmp_dir_obj;
    let store;
    beforeEach(() => {
      tmp_dir_obj = tmp.dirSync({ unsafeCleanup: true });
      tmp_dir_name = tmp_dir_obj.name;
    });
    afterEach(() => {
      tmp_dir_obj.removeCallback();
    });
    describe("generate_flask_command_line_args", () => {
      describe("Given an ElectronStore has been created in a temporary absolute path", () => {
        beforeEach(() => {
          store = main_utils.create_store({ file_path: tmp_dir_name });
        });
        test("When the function is invoked, Then the log file directory argument is set to the folder containing the store", () => {
          const actual_args = main_utils.generate_flask_command_line_args(
            store
          );

          expect(actual_args).toStrictEqual(
            expect.arrayContaining([
              "--log-file-dir=" +
                path.join(
                  path.dirname(store.path),
                  "logs_flask",
                  filename_prefix
                ),
            ])
          );
        });
        test("When the function is invoked, Then the expected-software-version argument is set to the value returned by get_current_app_version", () => {
          const spied_get_current_app_version = jest.spyOn(
            main_utils,
            "get_current_app_version"
          );

          const actual_args = main_utils.generate_flask_command_line_args(
            store
          );

          expect(actual_args).toStrictEqual(
            expect.arrayContaining([
              "--expected-software-version=" +
                spied_get_current_app_version.mock.results[0].value,
            ])
          );
        });

        test("When the function is invoked, Then the returned --initial-base64-settings encoded settings argument is supplied only containing the recording directory (since no ID exists in the store)", () => {
          const actual_args = main_utils.generate_flask_command_line_args(
            store
          );
          const expected_obj = {
            log_file_uuid: filename_prefix,
            recording_directory: path.join(tmp_dir_name, "recordings"),
            stored_customer_id: {
              id: "",
              password: "",
            },
            zipped_recordings_dir: path.join(
              tmp_dir_name,
              "recordings",
              "zipped_recordings"
            ),
            failed_uploads_dir: path.join(
              tmp_dir_name,
              "recordings",
              "failed_uploads"
            ),
          };

          const regex = "--initial-base64-settings=";
          const base_64_string = actual_args[2].replace(regex, "");
          const parsed_base64 = JSON.parse(
            url_safe_base64.decode(base_64_string).toString("utf8")
          );

          expect(parsed_base64).toStrictEqual(expected_obj);
        });

        test("When the function is invoked, Then subfolders are created for logs and recordings", () => {
          main_utils.generate_flask_command_line_args(store);
          expect(
            fs.existsSync(
              path.join(tmp_dir_name, "logs_flask", filename_prefix)
            )
          ).toBe(true);
          expect(fs.existsSync(path.join(tmp_dir_name, "recordings"))).toBe(
            true
          );
          expect(
            fs.existsSync(
              path.join(tmp_dir_name, "recordings", "zipped_recordings")
            )
          ).toBe(true);
          expect(
            fs.existsSync(
              path.join(tmp_dir_name, "recordings", "failed_uploads")
            )
          ).toBe(true);
        });
      });
    });

    describe("get_current_app_version", () => {
      test("Given that Electron is not actually running (because this is just a unit test), When the function is called, Then it returns the current version of the App", () => {
        const path_to_package_json = path.join(
          __dirname,
          "..",
          "..",
          "package.json"
        );
        const package_info = require(path_to_package_json);
        const expected = package_info.version;
        const actual = main_utils.get_current_app_version();

        expect(actual).toStrictEqual(expected);
      });
    });

    describe("create_store", () => {
      describe("Given create_store is called with a temporary absolute path", () => {
        beforeEach(() => {
          store = main_utils.create_store({ file_path: tmp_dir_name });
        });

        test("When a value is set in the store, Then it can be retrieved using get", () => {
          const the_key = "mykey";
          const expected_value = "myvalue";
          store.set(the_key, expected_value);
          const actual_value = store.get(the_key);
          expect(actual_value).toStrictEqual(expected_value);
        });
      });
    });
  });
});
