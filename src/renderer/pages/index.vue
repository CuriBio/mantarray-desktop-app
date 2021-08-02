<template>
  <div>
    <div class="div__y-axis-controls-container">
      <YAxisControls :height="'885px'" />
    </div>
    <div class="div__grid-of-waveforms">
      <div
        v-for="waveform_index in Array(6).keys()"
        :key="waveform_index"
        :style="
          'position: absolute; top: ' +
          (waveform_index % 2) * 422 +
          'px; left: ' +
          Math.floor(waveform_index / 2) * 524 +
          'px;'
        "
      >
        <ContinuousWaveform
          :display_waveform_idx="waveform_index"
          :x_label="'Time (seconds)'"
          :y_label="'Absolute Force (µN)'"
          :display_data_prior_to_current_timepoint="true"
        />
      </div>
    </div>
    <div class="div__x-axis-controls-container">
      <XAxisControls />
    </div>
  </div>
</template>

<script>
// Eli (3/29/21): adapted from https://stackoverflow.com/questions/31759367/using-console-log-in-electron-app
const log = require("electron-log");
const path = require("path");
const now = new Date();
const utc_month = (now.getUTCMonth() + 1).toString().padStart(2, "0"); // Eli (3/29/21) for some reason getUTCMonth returns a zero-based number, while everything else is a month, so adjusting here

const filename_prefix = `mantarray_log__${now.getUTCFullYear()}_${utc_month}_${now
  .getUTCDate()
  .toString()
  .padStart(2, "0")}_${now
  .getUTCHours()
  .toString()
  .padStart(2, "0")}${now
  .getUTCMinutes()
  .toString()
  .padStart(2, "0")}${now.getUTCSeconds().toString().padStart(2, "0")}_`;
log.transports.file.resolvePath = (variables) => {
  let filename;
  switch (process.type) {
    case "renderer":
      filename = filename_prefix + "renderer";
      break;
    case "worker":
      filename = filename_prefix + "worker";
      break;
    default:
      filename = filename_prefix + "main";
  }
  filename = filename + ".txt";
  return path.join(variables.libraryDefaultDir, "..", "logs_flask", filename);
};

console.log = log.log;
import {
  ContinuousWaveform,
  XAxisControls,
  YAxisControls,
} from "@curi-bio/mantarray-frontend-components";
export default {
  components: {
    ContinuousWaveform,
    XAxisControls,
    YAxisControls,
  },
  layout: "default",
};
</script>

<style type="text/css">
.div__y-axis-controls-container {
  top: 45px;
  position: absolute;
}
.div__x-axis-controls-container {
  position: absolute;
  left: 45px;
  top: 885px;
}
.div__grid-of-waveforms {
  position: absolute;
  top: 45px;
  left: 45px;
  height: 840px;
  width: calc(100vw - 353px);
  background-color: #4c4c4c;
}
</style>
