/**
 * By default, Nuxt.js is configured to cover most use cases.
 * This default configuration can be overwritten in this file
 * @link {https://nuxtjs.org/guide/configuration/}
 */
const path = require("path");
const node_modules_dir = path.join(__dirname, "..", "node_modules");
const ui_node_modules_dir = path.join(node_modules_dir, "@curi-bio", "ui", "node_modules");

module.exports = {
  alias: {
    vue$: path.join(ui_node_modules_dir, "vue", "dist", "vue.common.js"),
  },
  mode: "spa", // or 'universal'
  head: {
    title: "Stingray Controller",
    meta: [{ charset: "utf-8" }],
  },
  loading: false,
  dev: process.env.NODE_ENV === "DEV",
  modules: [path.join(ui_node_modules_dir, "bootstrap-vue", "nuxt")],
  bootstrapVue: {
    bootstrapCSS: false, // Or `css: false`
    bootstrapVueCSS: false, // Or `bvCSS: false`
  },

  css: [
    "@/assets/css/global.css",
    path.join(ui_node_modules_dir, "typeface-muli", "index.css"),
    path.join(ui_node_modules_dir, "typeface-anonymous-pro", "index.css"),
  ],

  rules: [
    { test: /\.css$/, use: "css-loader/locals" }, // https://github.com/aspnet/JavaScriptServices/issues/1154
  ],

  server: {
    port: 8080, // default: 3000
    host: "localhost", // default: localhost
  },
};
