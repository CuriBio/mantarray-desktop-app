const path = require("path");
const webpack = require("webpack");
const electron = require("electron");

const { Pipeline, Logger } = require("@xpda-dev/core");
const { ElectronLauncher } = require("@xpda-dev/electron-launcher");
const { ElectronBuilder } = require("@xpda-dev/electron-builder");
const { Webpack } = require("@xpda-dev/webpack-step");
const resourcesPath = require("./resources-path-provider");
const { DIST_DIR, MAIN_PROCESS_DIR, SERVER_HOST, SERVER_PORT } = require(path.join(__dirname, "config"));
const NuxtApp = require(path.join(__dirname, "renderer", "NuxtApp"));

const isDev = process.env.NODE_ENV === "development";
const channel = process.env.RELEASE_CHANNEL;

const build_electron = !(process.env.SUPPRESS_ELECTRON_BUILD === "true");

async function just_build_nuxt() {
  await webpackMain.build(isDev);
  await nuxt.build(isDev);
  process.exit(0);
}

const launcher = new ElectronLauncher({
  electronPath: electron,
  entryFile: path.join(DIST_DIR, "main", "index.js"),
});

let builder_config_path;
builder_config_path = path.join(__dirname, "..", `electron-builder-${channel}.yaml`);

const builder = new ElectronBuilder({
  processArgv: ["--config", builder_config_path, "--publish", "never"],
});

const webpackConfig = Webpack.getBaseConfig({
  entry: isDev ? path.join(MAIN_PROCESS_DIR, "index.dev.js") : path.join(MAIN_PROCESS_DIR, "index.js"),
  output: {
    filename: "index.js",
    path: path.join(DIST_DIR, "main"),
  },
  plugins: [
    new webpack.DefinePlugin({
      INCLUDE_RESOURCES_PATH: resourcesPath.mainProcess(),
      "process.env.DEV_SERVER_URL": `'${SERVER_HOST}:${SERVER_PORT}'`,
    }),
    // new webpack.IgnorePlugin(/\.(css|less)$/),
  ],
  devtool: "sourcemap",
});

const webpackMain = new Webpack({
  logger: new Logger("Main", "olive"),
  webpackConfig,
  launcher, // need to restart launcher after compilation
});

const nuxt = new NuxtApp(new Logger("Nuxt", "green"));

const pipe = new Pipeline({
  title: "Electron-nuxt",
  isDevelopment: isDev,
  steps: [webpackMain, nuxt],
  launcher,
  builder,
});

if (build_electron) {
  pipe.run();
} else {
  console.log(
    // allow-log
    "Nuxt will be built in Production mode, but the full Electron App will not be compiled"
  );

  just_build_nuxt();
}
