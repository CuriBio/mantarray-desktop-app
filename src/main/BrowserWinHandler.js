import { EventEmitter } from "events";
import { BrowserWindow, app, screen } from "electron";
const isProduction = process.env.NODE_ENV === "production";

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
    app.on("ready", () => {
      this._create();
      console.log("ready in winhandler after _create");
    });

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
    this.options.height = this.options.height / scale_factor;
    this.options.width = this.options.width / scale_factor;
    this.options.webPreferences.zoomFactor =
      this.options.webPreferences.zoomFactor / scale_factor;

    this.browserWindow = new BrowserWindow({
      ...this.options,
      webPreferences: {
        ...this.options.webPreferences,
        webSecurity: isProduction, // disable on dev to allow loading local resources
        nodeIntegration: true, // allow loading modules via the require () function
        devTools: !process.env.SPECTRON, // disable on e2e test environment
      },
    });
    this.browserWindow.on("closed", () => {
      // Dereference the window object
      this.browserWindow = null;
    });
    this.browserWindow.setContentSize(this.options.width, this.options.height); // Eli (6/20/20): for some odd reason, in Windows the EXE is booting up at slightly smaller dimensions than defined, so seeing if this extra command helps at all
    // Eli (6/21/20): the position seems to be defaulting to 1,87 instead of the 0,0 supplied in the args, unless this extra method is called
    this.browserWindow.setPosition(this.options.x, this.options.y);
    const win_position = this.browserWindow.getPosition();
    console.log("actual window position: " + win_position); // allow-log

    this._eventEmitter.emit("created");
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
    this._eventEmitter.once("created", () => {
      callback(this.browserWindow);
    });
  }

  /**
   *
   * @return {Promise<BrowserWindow>}
   */
  created() {
    return new Promise((resolve) => {
      this._eventEmitter.once("created", () => {
        resolve(this.browserWindow);
      });
    });
  }
}
