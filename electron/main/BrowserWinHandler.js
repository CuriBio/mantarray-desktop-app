/* eslint-disable */
import { EventEmitter } from "events";
import { BrowserWindow, app, screen, ipcMain } from "electron";
const DEV_SERVER_URL = process.env.DEV_SERVER_URL;
const isProduction = process.env.NODE_ENV === "production";
const isDev = process.env.NODE_ENV === "development";

import main_utils from "./utils.js"; // Eli (1/15/21): helping to be able to spy on functions within utils. https://stackoverflow.com/questions/49457451/jest-spyon-a-function-not-class-or-object-type

const create_store = main_utils.create_store;
let store = create_store();
const get_flask_logs_full_path = main_utils.get_flask_logs_full_path;

export default class BrowserWinHandler {
  /**
   * @param [options] {object} - browser window options
   * @param [allowRecreate] {boolean}
   */
  constructor(options, allowRecreate = true) {
    this._eventEmitter = new EventEmitter();
    this.allowRecreate = allowRecreate;
    this.options = options;
    this.browserWindow = null;
    this._createInstance();
  }

  _createInstance() {
    // This method will be called when Electron has finished
    // initialization and is ready to create browser windows.
    // Some APIs can only be used after this event occurs.
    if (app.isReady()) this._create();
    else {
      app.once("ready", () => {
        this._create();
        console.log("ready in winhandler after _create");
      });
    }

    // On macOS it's common to re-create a window in the app when the
    // dock icon is clicked and there are no other windows open.
    if (!this.allowRecreate) return;
    app.on("activate", () => this._recreate());
  }

  _create() {
    // In order to get display size to match in windows: https://stackoverflow.com/questions/59385237/electron-window-dimensions-vs-screen-resolution
    const scale_factor = screen.getPrimaryDisplay().scaleFactor;
    console.log("Screen size scale factor: " + scale_factor); // allow-log
    const { width, height } = screen.getPrimaryDisplay().workAreaSize;
    console.log("Sceen work area width " + width + " height " + height); // allow-log
    if (process.platform === "win32") {
      this.options.height = parseInt(this.options.target_height / scale_factor);
      this.options.width = parseInt(this.options.target_width / scale_factor);
    } else {
      this.options.height = height;
      this.options.width = width;
    }

    this.browserWindow = new BrowserWindow({
      ...this.options,
      webPreferences: {
        ...this.options.webPreferences,
        webSecurity: isProduction, // disable on dev to allow loading local resources
        nodeIntegration: true, // allow loading modules via the require () function
        contextIsolation: false, // https://github.com/electron/electron/issues/18037#issuecomment-806320028
        devTools: !process.env.SPECTRON, // disable on e2e test environment
      },
    });
    this.browserWindow.on("closed", () => {
      // Dereference the window object
      this.browserWindow = null;
    });

    let close = false;
    ipcMain.on("confirmation_response", (e, user_response) => {
      try {
        e.reply("confirmation_response", 200);

        let action;
        if (user_response === 1) {
          close = true;
          this.browserWindow.close();
          action = "confirmed";
        } else {
          action = "cancelled";
        }
        console.log(`user ${action} window closure`);
      } catch (e) {
        console.log("error in BrowserWinHandler trying to close");
      }
    });

    this.browserWindow.on("close", async (e) => {
      if (!close) {
        e.preventDefault();
        this.browserWindow.webContents.send("confirmation_request");
      }
    });

    this.browserWindow.once("ready-to-show", () => {
      const zoomFactor = this.options.width / this.options.target_width;
      this.browserWindow.webContents.setZoomFactor(zoomFactor);
    });

    this.browserWindow.setContentSize(this.options.width, this.options.height); // Eli (6/20/20): for some odd reason, in Windows the EXE is booting up at slightly smaller dimensions than defined, so seeing if this extra command helps at all
    // Eli (6/21/20): the position seems to be defaulting to 1,87 instead of the 0,0 supplied in the args, unless this extra method is called
    this.browserWindow.setPosition(this.options.x, this.options.y);
    const win_position = this.browserWindow.getPosition();
    console.log("actual window position: " + win_position); // allow-log

    this._eventEmitter.emit("created");

    ipcMain.once("beta_2_mode_request", (event) => {
      event.reply("beta_2_mode_response", store.get("beta_2_mode"));
    });
    ipcMain.once("stored_accounts_request", (event) => {
      event.reply("stored_accounts_response", {
        customer_id: store.get("customer_id"),
        usernames: store.get("usernames"),
      });
    });
    ipcMain.once("logs_flask_dir_request", (event) => {
      event.reply("logs_flask_dir_response", get_flask_logs_full_path(store));
    });
  }

  _recreate() {
    if (this.browserWindow === null) this._create();
  }

  /**
   * @callback onReadyCallback
   * @param {BrowserWindow}
   */

  /**
   *
   * @param callback {onReadyCallback}
   */
  onCreated(callback) {
    if (this.browserWindow !== null) return callback(this.browserWindow);
    this._eventEmitter.once("created", () => {
      callback(this.browserWindow);
    });
  }

  async loadPage(pagePath) {
    if (!this.browserWindow)
      return Promise.reject(new Error("The page could not be loaded before win 'created' event"));
    const serverUrl = isDev ? DEV_SERVER_URL : "app://./index.html";
    const fullPath = serverUrl + "#" + pagePath;
    await this.browserWindow.loadURL(fullPath);
  }

  /**
   *
   * @returns {Promise<BrowserWindow>}
   */
  created() {
    return new Promise((resolve) => {
      this._eventEmitter.once("created", () => {
        resolve(this.browserWindow);
      });
    });
  }
}
