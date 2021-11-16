import path from "path";
const { Menu } = require("electron");
const { centerWindow } = require("electron-util");
// const browser_win_handler_path = path.join(__dirname, "BrowserWinHandler");

// const BrowserWinHandler =require(browser_win_handler_path).BrowserWinHandler;
import BrowserWinHandler from "./BrowserWinHandler";
const isDev = process.env.NODE_ENV === "development";

const INDEX_PATH = path.join(__dirname, "..", "renderer", "index.html");
const DEV_SERVER_URL = process.env.DEV_SERVER_URL; // eslint-disable-line prefer-destructuring

const winHandler = new BrowserWinHandler({
  height: 930,
  width: 1920,
  x: 0, //  have the window launch in the top left corner of the screen. This is necessary since it takes the full width of the screen and so normally would try some weird way to center itself
  y: 0,
  webPreferences: {
    zoomFactor: 1.0,
  },
});

winHandler.onCreated((browserWindow) => {
  console.log("winHandler.onCreated event fired"); // allow-log
  // Eli (7/13/20): On windows, no matter what the x coordinate is set to, it doesn't seem to actually be on the left edge of the screen unless using this centerWindow function
  centerWindow({ window: browserWindow });
  // move the window up to the top
  const window_x = browserWindow.getPosition()[0];
  browserWindow.setPosition(window_x, 0);

  if (isDev) {
    browserWindow.loadURL(DEV_SERVER_URL);
  } else {
    browserWindow.loadFile(INDEX_PATH);
  }
});

const template = [
  {
    label: "Edit",
    submenu: [
      { label: "Undo", accelerator: "CmdOrCtrl+Z", selector: "undo:" },
      { label: "Redo", accelerator: "Shift+CmdOrCtrl+Z", selector: "redo:" },
      { type: "separator" },
      { label: "Cut", accelerator: "CmdOrCtrl+X", selector: "cut:" },
      { label: "Copy", accelerator: "CmdOrCtrl+C", selector: "copy:" },
      { label: "Paste", accelerator: "CmdOrCtrl+V", selector: "paste:" },
      {
        label: "Select All",
        accelerator: "CmdOrCtrl+A",
        selector: "selectAll:",
      },
    ],
  },
];

Menu.setApplicationMenu(Menu.buildFromTemplate(template));

// Menu.setApplicationMenu(null); // adapted from: https://stackoverflow.com/questions/39091964/remove-menubar-from-electron-app

export default winHandler;
