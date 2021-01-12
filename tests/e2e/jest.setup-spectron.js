// Adapted from Electron-Nuxt template
const path = require("path");
const fs = require("fs");
const yaml = require("js-yaml");

const electron_nuxt_config_path = path.join(
  __dirname,
  "..",
  "..",
  ".electron-nuxt",
  "config"
);
const electron_builder_config_path = path.join(
  __dirname,
  "..",
  "..",
  "electron-builder.yaml"
);
const package_path = path.join(__dirname, "..", "..", "package");

const { BUILD_DIR } = require(electron_nuxt_config_path);
const { DIST_DIR } = require(electron_nuxt_config_path);

const fileContents = fs.readFileSync(electron_builder_config_path, "utf8");
const builder_config_data = yaml.safeLoad(fileContents);

const product_name = builder_config_data.productName;

const { name: package_name } = require(package_path);

const YELLOW = "\x1B[33m";
const END = "\x1B[0m";

let relativeAppPath = "";

const os = process.platform;
if (os === "darwin") {
  relativeAppPath = `mac/${product_name}.app/Contents/MacOS/${product_name}`;
} else if (os === "win32" || os === "win64") {
  relativeAppPath = `win-unpacked/${product_name}.exe`;
} else if (os === "linux") {
  relativeAppPath = `linux-unpacked/${package_name.toLowerCase()}`;
}

const applicationPath = path.join(DIST_DIR, relativeAppPath); // Eli (6/15/20): in the original Electron-Nuxt template, this pointed to the BUILD_DIR, not the DIST_DIR...but I don't know the difference, and we happen to use DIST

if (!fs.existsSync(applicationPath)) {
  throw new Error(`${YELLOW}[Spectron setup]:${END} Application with path: '${applicationPath}' doesn't exist.
        First build your app ('npm run build') or set proper path to executable binary.`);
}

// process.env.APPLICATION_PATH = applicationPath

module.exports = async () => {
  process.env.APPLICATION_PATH = applicationPath;
};
