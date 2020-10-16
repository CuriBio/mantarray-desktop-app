// adapted from https://medium.com/@brandonaaskov/how-to-test-nuxt-stores-with-jest-9a5d55d54b28

// This section adapted from .electron-nuxt/index.js
const path = require("path");

const path_to_electron_nuxt = path.join(__dirname, ".electron-nuxt");

const path_to_resources_provider = path.join(
  path_to_electron_nuxt,
  "resources-path-provider"
);

const path_to_config = path.join(path_to_electron_nuxt, "config");

const path_to_nuxt_config = path.join(
  path_to_electron_nuxt,
  "renderer",
  "nuxt.config"
);

const path_to_nuxt_app = path.join(
  path_to_electron_nuxt,
  "renderer",
  "NuxtApp"
);

const resourcesPath = require(path_to_resources_provider);
const {
  DIST_DIR,
  MAIN_PROCESS_DIR,
  SERVER_HOST,
  SERVER_PORT,
} = require(path_to_config);
const NuxtApp = require(path_to_nuxt_app);

const isDev = process.env.NODE_ENV === "development";

//const nuxt = new NuxtApp(new Logger("Nuxt", "green"));
// ------------------------------

import { Nuxt, Builder } from "nuxt";
let nuxtConfig = require(path_to_nuxt_config);

// console.log('after imports')

// these boolean switches turn off the build for all but the store
const resetConfig = {
  loading: false,
  loadingIndicator: false,
  fetch: {
    client: false,
    server: false,
  },
  features: {
    store: true,
    layouts: false,
    meta: false,
    middleware: false,
    transitions: false,
    deprecations: false,
    validate: false,
    asyncData: false,
    fetch: false,
    clientOnline: false,
    clientPrefetch: false,
    clientUseUrl: false,
    componentAliases: false,
    componentClientOnly: false,
  },
  build: {
    indicator: false,
    terser: false,
  },
};

// we take our nuxt config, lay the resets on top of it,
// and lastly we apply the non-boolean overrides
const config = Object.assign({}, nuxtConfig, resetConfig, {
  mode: "spa",
  srcDir: nuxtConfig.srcDir,
  ignore: ["**/components/**/*", "**/layouts/**/*", "**/pages/**/*"],
});

const buildNuxt = async () => {
  const nuxt = new Nuxt(config);
  await new Builder(nuxt).build();
  return nuxt;
};

module.exports = async () => {
  const nuxt = await buildNuxt();

  // we surface this path as an env var now
  // so we can import the store dynamically later on
  process.env.buildDir = nuxt.options.buildDir;
};
