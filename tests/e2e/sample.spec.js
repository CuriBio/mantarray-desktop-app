// Based on https://livebook.manning.com/book/electron-in-action/chapter-13/39
// 'use strict';

/*

Docker attempts

docker pull mcr.microsoft.com/windows/servercore:ltsc2016

docker run --name test -it --mount type=bind,src=/docker,dst=/docker mcr.microsoft.com/windows/servercore:ltsc2016

# launch powershell
powershell


# install chocolaty
Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))

# install google chrome
choco install -y googlechrome --ignore-checksums

# install chromedriver
choco install -y chromedriver --ignore-checksums

# check versions
chromeDriver -v
(Get-Item "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe").VersionInfo

*/
const axios = require("axios");
import sinon from "sinon";
const child_process = require("child_process");
const resemble = require("resemblejs");

const ci = require("ci-info");
const path = require("path");
const Application = require("spectron").Application;
const flask_port = 4567;
const detect_port = require("detect-port");
import { spectron_page_visual_regression } from "@curi-bio/frontend-test-utils";

const is_windows = process.platform === "win32";

const base_screenshot_path = path.join(is_windows ? "windows" : "linux", "continuous-waveform");
const box_surrounding_version_number = {
  left: 237, // Eli (3/29/21): This VRT does still include the major version so that basics of text style and ability to extract the version number can be validated. This seems like a reasonable compromise between testing to make sure nothing is wrong, and not having a brittle test that needs to be updated everytime a minor or patch version bump happens.
  top: 910,
  right: 237 + 32,
  bottom: 910 + 12,
};

let sandbox;

/**
 * Eli (1/14/21) unsure exactly how this works. Copied from template at https://github.com/michalzaq12/electron-nuxt/blob/master/template/test/e2e/helpers.js
 *
 * @param {Object} client - Eli (1/14/21) unsure exactly how this works. Copied from template at https://github.com/michalzaq12/electron-nuxt/blob/master/template/test/e2e/helpers.js
 */
function addExtraCommands(client) {
  // http://v4.webdriver.io/api/utility/addCommand.html
  client.addCommand("hasNotError", async function (throwError = true) {
    const rendererLogs = await this.getRenderProcessLogs();
    const rendererErrors = rendererLogs.filter((log) => log.level === "ERROR");

    if (rendererErrors.length === 0) return true;
    if (throwError) return Promise.reject(new Error(rendererErrors[0].message));
    return false;
  });
}

/**
 * Eli (1/14/21) unsure exactly how this works. Copied from template at https://github.com/michalzaq12/electron-nuxt/blob/master/template/test/e2e/helpers.js
 *
 * @param {Object} client - Eli (1/14/21) unsure exactly how this works. Copied from template at https://github.com/michalzaq12/electron-nuxt/blob/master/template/test/e2e/helpers.js
 */
function addNuxtCommands(client) {
  // https://github.com/michalzaq12/electron-nuxt/blob/master/template/test/e2e/helpers.js
  /**
   * Eli (1/14/21) unsure exactly how this works. Copied from template at https://github.com/michalzaq12/electron-nuxt/blob/master/template/test/e2e/helpers.js
   *
   */
  async function ready() {
    // let output = "";
    // for (const property in this) {
    //   if (property == "waitUntilWindowLoaded") {
    //     output += property + ": " + this[property] + "; ";
    //   }
    // }

    await this.waitUntilWindowLoaded();
    await this.waitUntil(async () => {
      const result = await this.execute(() => !!window.$nuxt);
      return result.value;
    }, 15000);
  }

  /**
   * Eli (1/14/21) unsure exactly how this works. Copied from template at https://github.com/michalzaq12/electron-nuxt/blob/master/template/test/e2e/helpers.js
   *
   * @param {string} url - Eli (1/14/21) unsure exactly how this works. Copied from template at https://github.com/michalzaq12/electron-nuxt/blob/master/template/test/e2e/helpers.js
   *
   * @return {Promise} - Eli (1/15/21) I don't know what this returns...this is from the template
   */
  async function navigate(url) {
    await this.execute((url) => {
      window.$nuxt.$router.push(url);
    }, url);

    const ERROR_TEXT_SELECTOR = ".__nuxt-error-page > .error > .title";
    try {
      const errorText = await this.element(ERROR_TEXT_SELECTOR).getText();
      return Promise.reject(new Error(`Nuxt: ${errorText} (url: '${url}').`));
    } catch (e) {
      // if the element doesnt exist, do not throw any errors
    }
  }

  const clientPrototype = Object.getPrototypeOf(client);
  Object.defineProperty(clientPrototype, "nuxt", {
    get() {
      return {
        ready: ready.bind(client),
        navigate: navigate.bind(client),
      };
    },
  });
}

/**
 * Sleeps for an amount of time. Based on https://www.sitepoint.com/delay-sleep-pause-wait/
 * usage: await sleep(ms)
 *
 * @param {int} ms - number of milliseconds to sleep
 *
 * @return {Promise} - a resolved promise to sleep
 */
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Wait for Flask server to initialized
 *
 * @throws Will throw error if Flask never initializes (determined by port still being open)
 */
async function wait_for_flask_to_init() {
  for (let i = 0; i < 15; i++) {
    const detected_open_port = await detect_port(flask_port);
    if (detected_open_port !== flask_port) {
      return;
    }
    await sleep(1000);
  }
  throw new Error(`Port never came into use: ${flask_port}`);
}

/**
 * Wait for Flask server to reach CALIBRATION_NEEDED state
 *
 * @throws Will throw error if local server never reaches the CALIBRATION_NEEDED state
 */
async function wait_for_local_server_to_reach_calibration_needed() {
  for (let i = 0; i < 80 / 2; i++) {
    const response = await axios.get("http://localhost:4567/system_status");
    console.log(i); // allow-log
    console.log(response); // allow-log
    if (response.data.ui_status_code == "009301eb-625c-4dc4-9e92-1a4d0762465f") {
      // TODO (Eli 1/14/21): replace this string by importing the value from the frontend-components library
      await sleep(2000); // Eli (3/15/21): do an extra sleep because it seems like sporadically the screenshot is still in the initializing state
      return;
    }
    await sleep(2000);
  }
  throw new Error(`Server never reached CALIBRATION_NEEDED state`);
}

/**
 * Wait for Flask server to shut down
 *
 * @throws Will throw error if Flask never shuts down (determined by port still being occupied)
 */
async function wait_for_flask_to_be_shutdown() {
  for (let i = 0; i < 15; i++) {
    const detected_open_port = await detect_port(flask_port);
    if (detected_open_port === flask_port) {
      console.log("Flask successfully detected as shut down after " + i + " checks of the port."); // allow-log
      return;
    }
    await sleep(1000);
  }
  throw new Error(`Port never became open: ${flask_port}`);
}

describe("window_opening", () => {
  // TODO Tanner (7/29/21): Add E2E test for heatmap once the page is styled correctly

  afterAll(() => {
    console.log("at end of test suite");
  });

  beforeEach(async () => {
    sandbox = sinon.createSandbox();
    // const path_to_main_js = path.join(__dirname, "..", "..", "dist", "main");

    const app = new Application({
      path: process.env.APPLICATION_PATH, // electronPath,
      // args: [path_to_main_js], // should be root directory of repository, containing the main.js file for Electron
      chromeDriverArgs: [
        "--headless",
        "--disable-gpu",
        "--disable-infobars",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-extensions",
        "--window-size=1920,1080",
      ],
      env: {
        SPECTRON: true,
        ELECTRON_ENABLE_LOGGING: true,
        ELECTRON_ENABLE_STACK_DUMPING: true,
        ELECTRON_DISABLE_SECURITY_WARNINGS: true,
      },
      webdriverOptions: {
        width: 1920,
        height: 930,
      },
      waitTimeout: 10000, // time until app is started(?)
    });

    sandbox.the_app = app;

    console.log("about to start the app"); // allow-log

    const the_started_app = await app.start();

    console.log("app started"); // allow-log

    addExtraCommands(app.client);
    addNuxtCommands(app.client);

    console.log("waiting for flask server to initialize");
    await wait_for_flask_to_init();
    return the_started_app;
  }, 20000);

  // Eli (1/15/21): I don't know how to fix this...but just removing the `done` causes the test process not to work
  // eslint-disable-next-line jest/no-done-callback
  afterEach(async (done) => {
    console.log("checking if app is running during teardown"); // allow-log

    const app = sandbox.the_app;

    await app.client.getMainProcessLogs().then(function (logs) {
      logs.forEach(function (log) {
        console.log(log);
      });
    });

    if (app && app.isRunning()) {
      console.log("about to stop app"); // allow-log
      // adapted from https://stackoverflow.com/questions/51310500/spectron-test-leaves-window-open
      // get the main process PID
      const pid = await app.mainProcess.pid();

      // close the renderer window using its own js context
      // to get closer to the user action of closing the app
      // you could also use .stop() here
      // let main_process_logs; // = await app.client.getMainProcessLogs()
      // let render_process_logs = await app.client.getRenderProcessLogs();
      const stopped_app_return_code = await app.stop();
      console.log("stopped_app_return_code['running']: " + stopped_app_return_code["running"]); // allow-log
      // for (const [key, value] of Object.entries(stopped_app_return_code)) {
      //   console.log(` app.stop return code - ${key}: ${value}`); // allow-log
      // }
      // await app.stop();

      // await app.client.execute(() => {
      //     window.close();
      // });
      // main_process_logs = await app.client.getMainProcessLogs();
      try {
        const shutdown_response = await axios.get("http://localhost:4567/shutdown"); // Eli (1/18/21): `app.stop()` apparently isn't triggering the call to shutdown Flask, so manually doing it here
        console.log("Shutdown response: " + JSON.stringify(shutdown_response)); // allow-log
      } catch (e) {
        console.log("Error attempting to call shutdown route: " + e); // allow-log
      }

      await wait_for_flask_to_be_shutdown();

      console.log("app should be closed. Was ProcessID: " + pid); // allow-log
      // here, the app should be closed

      // console.log(main_process_logs);
      // console.log(render_process_logs)
      try {
        // check if PID is running using '0' signal (throw error if not)
        if (is_windows) {
          // child_process.execSync("Stop-Process -ID " + pid + " -Force"); // powershell command syntax
          child_process.execSync("taskkill /F /PID " + pid, {
            stdio: "inherit",
          });
        } else {
          process.kill(pid, 0);
        }
      } catch (e) {
        // error catched : the process was not running
        console.log("the app was confirmed to be closed: error message when attempting to kill it: " + e); // allow-log
        // do someting to end the test with success !
        done();
        return;
      }
      console.log("The app is still running...that should not happen"); // allow-log
      // no error, process is still running, stop it
      app.mainProcess.exit(1);
      // do someting to end the test with error
      // 6 / 0;
      done();
    }
  }, 30000);

  // test("Then it should initialize nuxt", async () => {
  //   const app = sandbox.the_app;
  //   const win = app.browserWindow;
  //   const client = app;

  //   await app.client.nuxt.ready();
  // }, 20000);
  // test("Then it should start the Python Flask server", async () => {
  //   const app = sandbox.the_app;
  //   const expected_value = "talkback";
  //   await app.client.nuxt.ready();
  //   await wait_for_flask_to_init();
  //   const echo_response = await axios.get(
  //     `http://localhost:${flask_port}/echo?input=${expected_value}`
  //   );

  //   expect(echo_response.data.my_json_key).toStrictEqual(expected_value);
  // }, 20000);

  test("When first initialized, Then it shows an initial window of the correct dimensions and position", async () => {
    const app = sandbox.the_app;
    const window_count = await app.client.getWindowCount();

    expect(window_count).toStrictEqual(1); // Please note that getWindowCount() will return 2 if `dev tools` are opened.
    const win = app.browserWindow;

    expect(await win.isMinimized()).toBe(false);
    expect(await win.isMaximized()).toBe(false);
    const { width, height } = await win.getBounds();
    console.log("Width: " + width + " height: " + height); // allow-log
    let expected_width;
    let expected_height;
    let expected_window_top;
    let expected_window_left;
    if (is_windows) {
      expected_width = 1936;
      expected_height = 969;
      expected_window_left = -8;
      expected_window_top = 0;
    } else {
      expected_width = 1920;
      expected_height = 930;
      if (ci.isCI) {
        expected_window_left = 0;
        expected_window_top = 0;
      } else {
        expected_window_left = 1; // for some reason the coordinate is 1 in Cloud9, but 0 in Ubuntu in Github CI
        expected_window_top = 23; // for some reason the coordinate is 23 in Cloud9, but 0 in Ubuntu in Github CI
      }
    }

    expect(width).toStrictEqual(expected_width); // Eli (6/14/20): If running on Cloud9, make sure to install the latest version of c9vnc repo or update the supervisord.conf file to have 1920x1080 dimensions
    expect(height).toStrictEqual(expected_height);
    const win_position = await win.getPosition();
    console.log("Window Position: " + win_position[0] + " " + win_position[1]); // allow-log
    expect(win_position[0]).toStrictEqual(expected_window_left); // when not maximized, there's a single extra pixel of border width on the edge
    expect(win_position[1]).toStrictEqual(expected_window_top); // takes into account the height of the menu

    const this_base_screenshot_path = path.join(base_screenshot_path);

    const screenshot_path = path.join(this_base_screenshot_path, "init");
    await wait_for_local_server_to_reach_calibration_needed();
    await sleep(3000);
    resemble.outputSettings({ ignoredBox: box_surrounding_version_number });
    await expect(spectron_page_visual_regression(app.browserWindow, screenshot_path)).resolves.toBe(true);
    resemble.outputSettings({ ignoredBox: undefined });
  }, 90000);
  test("When Calibrate is clicked (and waiting some time for calibration to finish), Then the screen shows the Calibrated state", async () => {
    const app = sandbox.the_app;
    await wait_for_local_server_to_reach_calibration_needed();
    const calibrate_button = await app.client.$(".svg__playback-desktop-player-controls-calibrate-button");
    await calibrate_button.click();

    await sleep(35000); // wait for calibration to occur and simulated barcode to populate
    const this_base_screenshot_path = path.join(base_screenshot_path);

    const screenshot_path = path.join(this_base_screenshot_path, "calibrated");

    resemble.outputSettings({ ignoredBox: box_surrounding_version_number });
    await expect(spectron_page_visual_regression(app.browserWindow, screenshot_path)).resolves.toBe(true);
    resemble.outputSettings({ ignoredBox: undefined });
  }, 90000);
});
