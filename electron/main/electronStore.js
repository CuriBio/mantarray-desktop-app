const path = require("path");
const electron = require("electron");
const Conf = require("conf");

/**
 * Electron store class.
 * @class
 */
export default class ElectronStore extends Conf {
  /**
   * @param {object} options electron store options
   */
  constructor(options) {
    options = {
      name: "config",
      ...options,
    };

    if (options.cwd) {
      if (!path.isAbsolute(options.cwd)) {
        options.cwd = path.join((electron.app || electron.remote.app).getPath("userData"), options.cwd);
      }
    } else {
      const defaultCwd = (electron.app || electron.remote.app).getPath("userData");
      options.cwd = defaultCwd;
    }

    options.configName = options.name;
    delete options.name;
    super(options);
  }

  /**
   *
   */
  openInEditor() {
    const open = electron.shell.openItem || electron.shell.openPath;
    open(this.path);
  }
}
