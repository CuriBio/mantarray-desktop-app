<template>
  <div>
    <div class="div__y-axis-controls-container">
      <YAxisControls :height="'930px'"></YAxisControls>
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
          :y_label="'Contraction Magnitude (microns)'"
          :display_data_prior_to_current_timepoint="true"
        ></ContinuousWaveform>
      </div>
    </div>
    <div class="div__x-axis-controls-container">
      <XAxisControls></XAxisControls>
    </div>
    <div class="div__top-bar-above-waveforms">
      <div class="div__recording-time-container">
        <RecordingTime></RecordingTime>
      </div>
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
  RecordingTime,
} from "@curi-bio/mantarray-frontend-components";
export default {
  components: {
    ContinuousWaveform,
    XAxisControls,
    YAxisControls,
    RecordingTime,
  },
  layout: "default",
  created() {
    this.$store.commit("waveform/set_y_axis_zoom_idx", 2);
    this.$store.commit("waveform/set_y_axis_zoom_levels", [
      { y_min: -100, y_max: 200 },
      { y_min: 0, y_max: 150 },

      { y_min: 50, y_max: 150 },
      { y_min: 50, y_max: 150 },
      { y_min: 50, y_max: 140 },
      { y_min: 50, y_max: 130 },
      { y_min: 55, y_max: 120 },
      { y_min: 60, y_max: 120 },
      { y_min: 60, y_max: 110 },
      { y_min: 65, y_max: 110 },
      { y_min: 70, y_max: 110 },
      { y_min: 70, y_max: 105 },
      { y_min: 75, y_max: 105 },
      { y_min: 80, y_max: 105 },
      { y_min: 85, y_max: 105 },
      { y_min: 90, y_max: 105 },
      { y_min: 94, y_max: 102 },
      { y_min: 96, y_max: 100 },
    ]);

    this.$store.commit("waveform/set_x_axis_zoom_idx", 2);
    this.$store.commit("waveform/set_x_axis_zoom_levels", [
      { x_scale: 30 * 100000 },
      { x_scale: 15 * 100000 },
      { x_scale: 5 * 100000 },
      { x_scale: 2 * 100000 },
      { x_scale: 1 * 100000 },
    ]);
    this.$store.dispatch("flask/start_status_pinging");

    console.log("Initial view has been rendered"); // allow-log
  },
  mounted() {},
};
</script>

<style type="text/css">
.div__y-axis-controls-container {
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
.div__top-bar-above-waveforms {
  position: absolute;
  left: 45px;
  background-color: #111111;
  height: 45px;
  width: calc(100vw - 353px);
}
/* alignment within a div: https://jsfiddle.net/72aqsq83/1/ */
.div__recording-time-container {
  float: right;
  position: relative;
  height: 45px;
  width: 215px;
}
</style>
