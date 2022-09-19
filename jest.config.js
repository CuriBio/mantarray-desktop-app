module.exports = {
  globalSetup: "<rootDir>/jest.setup.js", // (Eli 2/24/20) adapted from https://medium.com/@brandonaaskov/how-to-test-nuxt-stores-with-jest-9a5d55d54b28
  setupFilesAfterEnv: ["<rootDir>/jest.setup-failure-on-warnings.js"], // (Eli 3/2/20) adapted from https://medium.com/@chris.washington_60485/vue-jest-properly-catch-unhandledpromiserejectionwarning-and-vue-warn-errors-in-jest-unit-tests-fcc45269146b
  moduleNameMapper: {
    // we can use "@/components/item.vue" to access components in a simpler way
    "^@/(.*)$": "<rootDir>/src/$1",
    // "^@/(.*)$": "<rootDir>/$1"
    // the 'create-api' alias is defined in webpack, so we need to define it for jest too
    // '^create-api$': '<rootDir>/src/api/create-api-client.js',
  },
  modulePathIgnorePatterns: ["<rootDir>/dist"],
  // the files Jest should seach for
  testRegex: "tests/unit-jest/.*.spec.js",
  // the file types we want jest to accept
  moduleFileExtensions: [
    "js",
    "json",
    // tell Jest to handle `*.vue` files
    "vue",
    "ts",
    "tsx",
  ],
  // transformations we want jest to apply
  transform: {
    // process `*.vue` files with `vue-jest`
    "^.+\\.vue$": "vue-jest",
    // process js files with jest
    "^.+\\.js$": "babel-jest",
    // process assets with transform stub
    ".+\\.(css|styl|less|sass|scss|svg|png|jpg|ttf|woff|woff2)$": "jest-transform-stub",
  },
  // we will use this to create snapshot tests
  snapshotSerializers: ["jest-serializer-vue"],
  // used for jsdom to mimic a real browser with a real url
  testURL: "http://localhost/",
  // we should collect coverage
  collectCoverage: true,

  // set a directory for coverage cache
  coverageDirectory: "<rootDir>/tests/__coverage__/unit",

  // set patterns to ignore for coverage
  coveragePathIgnorePatterns: ["/node_modules", "test_utils", ".nuxt"],
};
