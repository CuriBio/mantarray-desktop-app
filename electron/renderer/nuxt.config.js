/**
 * By default, Nuxt.js is configured to cover most use cases.
 * This default configuration can be overwritten in this file
 * @link {https://nuxtjs.org/guide/configuration/}
 */
const path = require("path");
const node_modules_dir = path.join(__dirname, "..", "..", "node_modules");
module.exports = {
  mode: "spa", // or 'universal'
  head: {
    title: "Mantarray Software",
    meta: [{ charset: "utf-8" }],
  },
  loading: false,
  dev: process.env.NODE_ENV === "DEV",
  modules: ["bootstrap-vue/nuxt"],
  bootstrapVue: {
    bootstrapCSS: false, // Or `css: false`
    bootstrapVueCSS: false, // Or `bvCSS: false`
  },

  css: [
    "@/assets/css/global.css",
    path.join(node_modules_dir, "typeface-muli", "index.css"),
    path.join(node_modules_dir, "typeface-anonymous-pro", "index.css"),
  ],
  rules: [
    { test: /\.css$/, use: "css-loader/locals" }, // https://github.com/aspnet/JavaScriptServices/issues/1154
  ],

  server: {
    port: 8080, // default: 3000
    host: "localhost", // default: localhost
  },
};
