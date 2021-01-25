const tmp = require("tmp");
const yaml = require("js-yaml");
tmp.setGracefulCleanup(); // Eli (7/13/20): According to the docs, this is supposed to enforce automatic deletion of the folders at the end of running the process, but it does not appear to be working. Manual cleanup seems to be required.
// const { create_store } = require("@/main/utils.js");
import ElectronStore from "@/main/electron_store";

import main_utils from "@/main/utils.js"; // Eli (1/15/21): helping to be able to spy on functions within utils. https://stackoverflow.com/questions/49457451/jest-spyon-a-function-not-class-or-object-type

const mock_electron_store = "bob";

jest.mock("@/main/electron_store", () => {
  return jest.fn().mockImplementation(function () {
    return mock_electron_store;
  });
});

const sinon = require("sinon");

const sandbox = sinon.createSandbox({
  useFakeTimers: false, // Eli (6/14/20): fakeTimers can mess with Jest's builtin timers for timeouts for the tests. If you need to fake things about time, do so carefully, such as with sandbox.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
});
describe("electron_store", () => {
  afterEach(() => {
    jest.restoreAllMocks();
    ElectronStore.mockClear();
    sandbox.restore();
  });

  describe("create_store", () => {
    let tmp_dir_obj;
    // let tmp_dir_name;
    beforeEach(() => {
      tmp_dir_obj = tmp.dirSync({ unsafeCleanup: true });

      // tmp_dir_name = tmp_dir_obj.name;
      // console.log("Dir: ", tmp_dir_name);
    });
    afterEach(() => {
      tmp_dir_obj.removeCallback();
    });

    test("When called with default arguments, Then a ElectronStore is called with cwd undefined, file name config, and yaml formatting", async function () {
      // TODO (Eli 7/14/20): test the following also 'and the result of ElectronStore constructor is returned'  currently Jest is just returning mockConstructor
      main_utils.create_store();
      expect(ElectronStore).toHaveBeenCalledTimes(1);
      expect(ElectronStore).toHaveBeenCalledWith(
        expect.objectContaining({
          cwd: undefined,
          name: "mantarray_controller_config",
          fileExtension: "yaml",
          serialize: yaml.dump,
          deserialize: yaml.load,
        })
      );
    });
    test("When called with specified arguments, Then a ElectronStore is called with cwd matching file_path and file name matching file_name", async function () {
      const expected_path = "blah/things/places";
      const expected_file_name = "a_config";
      main_utils.create_store({
        file_path: expected_path,
        file_name: expected_file_name,
      });
      expect(ElectronStore).toHaveBeenCalledTimes(1);
      expect(ElectronStore).toHaveBeenCalledWith(
        expect.objectContaining({
          cwd: expected_path,
          name: expected_file_name,
        })
      );
    });
  });
});
