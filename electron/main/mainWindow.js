const { Menu } = require("electron");
const { centerWindow } = require("electron-util");

import BrowserWinHandler from "./BrowserWinHandler";

const winHandler = new BrowserWinHandler({
  targetHeight: 930,
  targetWidth: 1920,
  maxHeight: 989, // required to offset the hidden menu bar that holds keyboard shortcuts
  x: 0, //  have the window launch in the top left corner of the screen. This is necessary since it takes the full width of the screen and so normally would try some weird way to center itself
  y: 0,
  webPreferences: {
    zoomFactor: 1.0,
  },
});

winHandler.onCreated((browserWindow) => {
  console.log("winHandler.onCreated event fired"); // allow-log
  // Eli (7/13/20): On windows, no matter what the x coordinate is set to, it doesn't seem to actually be on the left edge of the screen unless using this centerWindow function
  browserWindow.setMenuBarVisibility(false);

  centerWindow({ window: browserWindow });
  // move the window up to the top
  const windowX = browserWindow.getPosition()[0];
  browserWindow.setPosition(windowX, 0);

  winHandler.loadPage("/");
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

export default winHandler;
