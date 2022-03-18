"use strict";
/**
 * Usage: node s3publisher.js --file=MyApp-v1.0.0.exe --channel=beta
 * Options:
 * --file: distributable file, normally nsis installer, dmg, snap, etc
 * --buildDir: (optional) folder where the files are located (default: ./build)
 * --channel: (optional) channel to upload yml
 */
const { MultiProgress } = require("electron-publish/out/multiProgress");
const { CancellationToken } = require("builder-util-runtime");
// is using s3 but you could choose another one under the 'app-builder-lib/out/publish' folder
const S3Publisher = require("app-builder-lib/out/publish/s3/s3Publisher").default;
// const S3Publisher = require('electron-publisher-s3').default;
const argv = require("yargs").argv;

const buildDir = argv.buildDir || "./dist/";
const channel = argv.channel || "unstable";
const bucket = argv.bucket || "downloads.curibio.com//software";

const publisherContext = {
  cancellationToken: new CancellationToken(),
  progress: new MultiProgress(),
};
// it uses the same config: https://www.electron.build/configuration/publish#s3options
const publisherInfo = {
  path: null,
  provider: "s3",
  channel: channel,
  bucket: bucket,
  region: "us-east-1",
};
const publisher = new S3Publisher(publisherContext, publisherInfo);
const upload = async () => {
  try {
    await Promise.all([
      publisher.upload({ file: `${buildDir}/${argv.file}` }),
      publisher.upload({ file: `${buildDir}/${argv.file}.blockmap` }),
      publisher.upload({ file: `${buildDir}/${channel}.yml` }),
    ]);
  } catch (err) {
    console.error("Publisher Failed", err);
  }
};

upload();
