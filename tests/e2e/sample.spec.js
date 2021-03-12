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
const path = require("path");
const Application = require("spectron").Application;
const flask_port = 4567;
const detect_port = require("detect-port");
import { spectron_page_visual_regression } from "@curi-bio/frontend-test-utils";

const is_windows = process.platform === "win32";

const base_screenshot_path = path.join("continuous-waveform");

// const { test_with_Spectron } = require('vue-cli-plugin-electron-builder') // may only work with Vue 3 https://nklayman.github.io/vue-cli-plugin-electron-builder/guide/testingAndDebugging.html#testing

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
  for (let i = 0; i < 10; i++) {
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
    if (
      response.data.ui_status_code == "009301eb-625c-4dc4-9e92-1a4d0762465f"
    ) {
      // TODO (Eli 1/14/21): replace this string by importing the value from the frontend-components library
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
  for (let i = 0; i < 10000; i++) {
    const detected_open_port = await detect_port(flask_port);
    if (detected_open_port === flask_port) {
      return;
    }
  }
  throw new Error(`Port never became open: ${flask_port}`);
}

describe("window_opening", () => {
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

    // attempt to use webDriverIO (the 'client') to directly set the window size...since other approaches using chromeDriverArgs or webdriverOptions were not working in Windows CodeBuild
    // console.log(the_started_app.client.browser);
    // console.log(JSON.stringify(the_started_app.client));
    // console.log(await the_started_app.client.getWindowCount());
    // console.log(typeof the_started_app.client);
    // const all_function = Object.getOwnPropertyNames(
    //   Object.getPrototypeOf(the_started_app.client.window)
    // ).filter((m) => "function" === typeof the_started_app.client.window[m]);
    // console.log(all_function);
    // for (let i = 0; i < all_function.length; i++) {
    //   console.log(all_function[i]);
    // }

    // Object.getOwnPropertyNames(the_started_app.client).filter(function (p) {
    //   return typeof the_started_app.client[p] === "function";
    // })
    // );
    // const the_time=await the_started_app.client.getWindowBounds();
    // console.log(the_time)
    // await the_started_app.client.setViewportSize({width:1920, height:1080},true);

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
      console.log("about to stop app. Platform is windows? " + is_windows); // allow-log
      // adapted from https://stackoverflow.com/questions/51310500/spectron-test-leaves-window-open
      // get the main process PID
      const pid = await app.mainProcess.pid();

      // close the renderer window using its own js context
      // to get closer to the user action of closing the app
      // you could also use .stop() here
      // let main_process_logs; // = await app.client.getMainProcessLogs()
      // let render_process_logs = await app.client.getRenderProcessLogs();
      // const stopped_app_return_code = await app.stop();
      await app.stop();

      // await app.client.execute(() => {
      //     window.close();
      // });
      // main_process_logs = await app.client.getMainProcessLogs();
      try {
        const shutdown_response = await axios.get(
          "http://localhost:4567/shutdown"
        ); // Eli (1/18/21): `app.stop()` apparently isn't triggering the call to shutdown Flask, so manually doing it here
        console.log("Shutdown response: " + shutdown_response); // allow-log
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
          child_process.execSync("taskkill /F /PID " + pid);
        } else {
          process.kill(pid, 0);
        }
      } catch (e) {
        // error catched : the process was not running
        console.log(
          "the app was confirmed to be closed: error message when attempting to kill it: " +
            e
        ); // allow-log
        // do someting to end the test with success !
        done();
        return;
      }
      console.log("The app is still running...that should not happen"); // allow-log
      // no error, process is still running, stop it
      app.mainProcess.exit(1);
      // do someting to end the test with error
      6 / 0;
    }
  }, 20000);

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
    // expect(width).toStrictEqual(1920); // Eli (6/14/20): If running on Cloud9, make sure to install the latest version of c9vnc repo or update the supervisord.conf file to have 1920x1080 dimensions
    // expect(height).toStrictEqual(930);
    const win_position = await win.getPosition();
    console.log("Window Position: " + win_position[0] + " " + win_position[1]); // allow-log
    // expect(win_position[0]).toStrictEqual(1); // when not maximized, there's a single extra pixel of border width on the edge
    // expect(win_position[1]).toStrictEqual(23); // takes into account the height of the menu

    const this_base_screenshot_path = path.join(base_screenshot_path);

    const screenshot_path = path.join(this_base_screenshot_path, "init");
    await wait_for_local_server_to_reach_calibration_needed();
    await expect(
      spectron_page_visual_regression(app.browserWindow, screenshot_path)
    ).resolves.toBe(true);
  }, 90000);
});
