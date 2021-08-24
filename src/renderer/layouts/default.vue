<template>
  <div>
    <div class="div__sidebar">
      <div class="div__sidebar-page-divider" />
      <div class="div__plate-barcode-container">
        <PlateBarcode />
      </div>
      <div class="div__plate-navigator-container">
        <PlateNavigator />
      </div>
      <div class="div__status-bar-container">
        <StatusBar />
      </div>
      <div class="div__player-controls-container">
        <DesktopPlayerControls />
      </div>
      <span class="span__screen-view-options-text">Screen View Options</span>
      <div class="div__screen-view-container">
        <div class="div__waveform-screen-view">
          <!-- Default view is waveform screen -->
          <NuxtLink to="/">
            <img src="../assets/img/waveform-screen-view.png" />
          </NuxtLink>
        </div>
        <div class="div__heatmap-screen-view">
          <NuxtLink to="/heatmap">
            <img src="../assets/img/heatmap-screen-view.png" />
          </NuxtLink>
        </div>
      </div>
      <div class="div__simulation-mode-container">
        <SimulationMode />
      </div>
      <span class="span__copyright"
        >&copy;{{ current_year }} Curi Bio. All Rights Reserved. Version:
        {{ package_version }}
      </span>
    </div>
    <div class="div__top-bar-above-waveforms">
      <div class="div__recording-time-container">
        <RecordingTime />
      </div>
    </div>

    <div class="div__nuxt-page">
      <nuxt />
    </div>
  </div>
</template>
<script>
import {
  PlateNavigator,
  PlateBarcode,
  DesktopPlayerControls,
  StatusBar,
  SimulationMode,
  RecordingTime,
} from "@curi-bio/mantarray-frontend-components";

// const pkginfo = require('pkginfo')(module, 'version');
const dummy_electron_app = {
  getVersion() {
    return "0.0.0";
  },
};
const electron_app =
  process.env.NODE_ENV === "test"
    ? dummy_electron_app
    : require("electron").remote.app;
export default {
  components: {
    PlateNavigator,
    PlateBarcode,
    DesktopPlayerControls,
    StatusBar,
    SimulationMode,
    RecordingTime,
  },
  data: function () {
    return {
      // package_version: module.exports.version,
      package_version: electron_app.getVersion(), // Eli (7/13/20): This only displays the application version when running from a built application---otherwise it displays the version of Electron that is installed
      current_year: "2021", // new Date().getFullYear(),
    };
  },
  created: function () {
    // init store values needed in pages here since this side bar is only created once

    this.$store.commit("data/set_heatmap_values", {
      "Twitch Force": { data: [...Array(24)].map((e) => Array(0)) },
      "Twitch Frequency": { data: [...Array(24)].map((e) => Array(0)) },
    });

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
};
</script>

<style type="text/css">
body {
  background-color: #000000;
}
.div__nuxt-page {
  position: absolute;
  top: 0px;
  left: 289px;
}

.div__top-bar-above-waveforms {
  position: absolute;
  left: 289px;
  background-color: #111111;
  height: 45px;
  width: calc(100vw - 289px);
}
.div__recording-time-container {
  float: right;
  position: relative;
  height: 45px;
  width: 215px;
}

.div__sidebar {
  background-color: #1c1c1c;
  position: absolute;
  top: 0px;
  left: 0px;
  height: 930px;
  width: 287px;
}
.div__sidebar-page-divider {
  position: absolute;
  top: 0px;
  left: 287px;
  width: 2px;
  height: 930px;
  background-color: #0e0e0e;
}
.div__plate-barcode-container {
  position: absolute;
  top: 45px;
  left: 0px;
}
.div__plate-navigator-container {
  position: absolute;
  top: 79px;
  left: 0px;
}
.div__status-bar-container {
  position: absolute;
  top: 256px;
  left: 0px;
}
.div__player-controls-container {
  position: absolute;
  top: 291px;
  left: 0px;
}
.div__screen-view-container {
  position: absolute;
  top: 400px;
  width: 287px;
  display: grid;
  grid-template-columns: 50% 50%;
  justify-items: center;
}
.span__screen-view-options-text {
  line-height: 100%;
  position: absolute;
  width: 207px;
  height: 23px;
  left: 11px;
  top: 372px;
  padding: 5px;
  user-select: none;
  font-size: 16px;
  color: #ffffff;
  text-align: left;
}
.div__waveform-screen-view- {
  grid-column: 1 / 2;
}
.div__heatmap-screen-view- {
  grid-column: 2;
}
.div__simulation-mode-container {
  position: absolute;
  top: 875px;
}
.span__copyright {
  position: absolute;
  z-index: 99;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
  box-sizing: border-box;
  line-height: 100%;
  overflow: hidden;
  width: 286px;
  height: 16px;
  top: 907px;
  left: -0.252101px;
  padding: 5px;
  user-select: none;
  font-family: Muli;
  font-weight: normal;
  font-style: normal;
  text-decoration: none;
  font-size: 9px;
  color: #ffffff;
  text-align: center;
}
</style>
