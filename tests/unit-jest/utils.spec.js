const path = require("path");
const fs = require("fs");
const tmp = require("tmp");
tmp.setGracefulCleanup(); // Eli (7/13/20): According to the docs, this is supposed to enforce automatic deletion of the folders at the end of running the process, but it does not appear to be working. Manual cleanup seems to be required.
const url_safe_base64 = require("urlsafe-base64");
const {
  create_store,
  generate_flask_command_line_args,
} = require("@/main/utils.js");

const sinon = require("sinon");
// const sinon_helpers = require("sinon-helpers");

const sandbox = sinon.createSandbox({
  useFakeTimers: false, // Eli (6/14/20): fakeTimers can mess with Jest's builtin timers for timeouts for the tests. If you need to fake things about time, do so carefully, such as with sandbox.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
});

const generic_id_info = {
  uuid: "14b9294a-9efb-47dd-a06e-8247e982e196",
  nickname: "Big Pharma",
  api_key: "zaCELgL.0imfnc8mVLWwsAawjYr4Rx-Af50DDqtlx",
  user_account_ids: [
    {
      uuid: "0288efbc-7705-4946-8815-02701193f766",
      nickname: "John Smith",
    },
  ],
};
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
          store = create_store({ file_path: tmp_dir_name });
        });
        test("When the function is invoked, Then the log file directory argument is set to the folder containing the store", () => {
          const actual_args = generate_flask_command_line_args(store);
          expect(actual_args).toStrictEqual(
            expect.arrayContaining([
              "--log-file-dir=" +
                path.join(path.dirname(store.path), "logs_flask"),
            ])
          );
        });
        test("When the function is invoked, Then the returned --initial-base64-settings encoded settings argument is supplied only containing the recording directory (since no ID exists in the store)", () => {
          const actual_args = generate_flask_command_line_args(store);
          const json_str = JSON.stringify({
            recording_directory: path.join(tmp_dir_name, "recordings"),
          });

          const buf = Buffer.from(json_str, "utf8");
          const expected_encoded = url_safe_base64.encode(buf);
          expect(actual_args).toStrictEqual(
            expect.arrayContaining([
              "--initial-base64-settings=" + expected_encoded,
            ])
          );
        });
        test("Given the store has a customer and user account ID, When the function is invoked, Then the returned --initial-base64-settings encoded settings argument contains the current user account and customer account IDs from the store and the recording directory", () => {
          const id_list = store.get("customer_account_ids");
          id_list.push(generic_id_info);
          store.set("customer_account_ids", id_list);

          const actual_args = generate_flask_command_line_args(store);
          const json_str = JSON.stringify({
            recording_directory: path.join(tmp_dir_name, "recordings"),
            customer_account_uuid: "14b9294a-9efb-47dd-a06e-8247e982e196",
            user_account_uuid: "0288efbc-7705-4946-8815-02701193f766",
          });

          const buf = Buffer.from(json_str, "utf8");
          const expected_encoded = url_safe_base64.encode(buf);
          expect(actual_args).toStrictEqual(
            expect.arrayContaining([
              "--initial-base64-settings=" + expected_encoded,
            ])
          );
        });
        test("When the function is invoked, Then subfolders are created for logs and recordings", () => {
          generate_flask_command_line_args(store);
          expect(fs.existsSync(path.join(tmp_dir_name, "logs_flask"))).toBe(
            true
          );
          expect(fs.existsSync(path.join(tmp_dir_name, "recordings"))).toBe(
            true
          );
        });
      });
    });

    describe("create_store", () => {
      describe("Given create_store is called with a temporary absolute path", () => {
        beforeEach(() => {
          store = create_store({ file_path: tmp_dir_name });
        });

        test("When a value is set in the store, Then it can be retrieved using get", () => {
          const the_key = "mykey";
          const expected_value = "myvalue";
          store.set(the_key, expected_value);
          const actual_value = store.get(the_key);
          expect(actual_value).toStrictEqual(expected_value);
        });
        test("When for customer account ids and account ID index and user ID index are accessed, Then they return the default value of an empty list", () => {
          let actual_value = store.get("customer_account_ids");
          expect(actual_value).toStrictEqual([]);
          actual_value = store.get("active_customer_account_index");
          expect(actual_value).toStrictEqual(0);
          actual_value = store.get("active_user_account_index");
          expect(actual_value).toStrictEqual(0);
        });
        test("When a customer account ID is added, Then a new store instance can load it", () => {
          const id_list = store.get("customer_account_ids");
          id_list.push(generic_id_info);
          store.set("customer_account_ids", id_list);

          const new_store = create_store({ file_path: tmp_dir_name });
          const actual_id_info = new_store.get("customer_account_ids")[0];

          expect(actual_id_info).toStrictEqual(generic_id_info);
        });
      });
    });
  });
});
