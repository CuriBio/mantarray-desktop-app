<template>
  <div>
    <div class="div__sidebar">
      <div class="div__sidebar-page-divider"></div>
      <div class="div__plate-barcode-container">
        <PlateBarcode></PlateBarcode>
      </div>
      <div class="div__plate-navigator-container">
        <PlateNavigator></PlateNavigator>
      </div>
      <div class="div__status-bar-container">
        <StatusBar></StatusBar>
      </div>
      <div class="div__player-controls-container">
        <DesktopPlayerControls></DesktopPlayerControls>
      </div>
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
        <SimulationMode></SimulationMode>
      </div>
      <span class="span__copyright"
        >&copy;{{ current_year }} Curi Bio. All Rights Reserved. Version:
        {{ package_version }}
      </span>
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
} from "@curi-bio/mantarray-frontend-components";

// const pkginfo = require('pkginfo')(module, 'version');
const electron_app = require("electron").remote.app;
export default {
  components: {
    PlateNavigator,
    PlateBarcode,
    DesktopPlayerControls,
    StatusBar,
    SimulationMode,
  },
  data: function () {
    return {
      // package_version: module.exports.version,
      package_version: electron_app.getVersion(), // Eli (7/13/20): This only displays the application version when running from a built application---otherwise it displays the version of Electron that is installed
      current_year: "2021", // new Date().getFullYear(),
    };
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
  left: 20px;
  top: 400px;
}
.div__waveform-screen-view- {
  position: absolute;
  left: 5px;
}
.div__heatmap-screen-view- {
  position: absolute;
  left: 185px;
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
