<template>
  <div>
    <div class="div__sidebar">
      <div class="div__sidebar-page-divider" />
      <div class="div__plate-barcode-container">
        <BarcodeViewer />
      </div>
      <div class="div__plate-navigator-container">
        <PlateNavigator />
      </div>
      <div class="div__status-bar-container">
        <StatusBar :confirmation_request="confirmation_request" @send_confirmation="send_confirmation" />
      </div>
      <div class="div__player-controls-container">
        <DesktopPlayerControls @save_customer_id="save_customer_id" />
      </div>

      <!-- Beta 2 specific components -->
      <div v-if="beta_2_mode">
        <div class="div__stim-barcode-container">
          <BarcodeViewer :barcode_type="'stim_barcode'" />
        </div>
        <div class="div__status-bar-container" :style="'top: 455px;'">
          <StatusBar
            :confirmation_request="confirmation_request"
            :stim_specific="true"
            @send_confirmation="send_confirmation"
          />
        </div>
        <div class="div__stimulation_controls-controls-icon-container">
          <StimulationControls />
          <NuxtLink to="/stimulationstudio">
            <div
              v-b-popover.hover.bottom="'Click to view Stimulation Studio'"
              :title="'Stimulation Studio'"
              class="div__stim-studio-screen-view"
            />
          </NuxtLink>
        </div>
      </div>

      <span
        class="span__screen-view-options-text"
        :class="[
          beta_2_mode
            ? 'span__screen-view-options-text--beta-2-mode'
            : 'span__screen-view-options-text--beta-1-mode',
        ]"
      >
        Screen View Options
      </span>
      <div
        class="div__screen-view-container"
        :class="[
          beta_2_mode ? 'div__screen-view-container--beta-2-mode' : 'div__screen-view-container--beta-1-mode',
        ]"
      >
        <div class="div__waveform-screen-view">
          <!-- Default view is waveform screen -->
          <NuxtLink to="/">
            <img
              v-b-popover.hover.bottom="'Click to view Live View'"
              :title="'Live View'"
              src="../assets/img/waveform-screen-view.png"
            />
          </NuxtLink>
        </div>
        <div class="div__heatmap-screen-view">
          <NuxtLink to="/heatmap">
            <img
              v-b-popover.hover.bottom="'Click to view Heat Map'"
              :title="'Heat Map'"
              src="../assets/img/heatmap-screen-view.png"
            />
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
      <div class="div__recording-status-container">
        <UploadFilesWidget />
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
  BarcodeViewer,
  DesktopPlayerControls,
  StatusBar,
  SimulationMode,
  RecordingTime,
  StimulationControls,
  UploadFilesWidget,
} from "@curi-bio/mantarray-frontend-components";
import { ipcRenderer } from "electron";
import { mapState } from "vuex";
const log = require("electron-log");
import path from "path";
import Vue from "vue";
import BootstrapVue from "bootstrap-vue";
import { VBPopover } from "bootstrap-vue";
// Note: Vue automatically prefixes the directive name with 'v-'
Vue.directive("b-popover", VBPopover);
Vue.use(BootstrapVue);
// const pkginfo = require('pkginfo')(module, 'version');
const dummy_electron_app = {
  getVersion() {
    return "0.0.0";
  },
};
const electron_app = process.env.NODE_ENV === "test" ? dummy_electron_app : require("electron").remote.app;

export default {
  components: {
    PlateNavigator,
    BarcodeViewer,
    DesktopPlayerControls,
    StatusBar,
    SimulationMode,
    RecordingTime,
    StimulationControls,
    UploadFilesWidget,
  },
  data: function () {
    return {
      // package_version: module.exports.version,
      package_version: electron_app.getVersion(), // Eli (7/13/20): This only displays the application version when running from a built application---otherwise it displays the version of Electron that is installed
      current_year: "2022",
      confirmation_request: false,
      beta_2_mode: process.env.SPECTRON || undefined,
      request_stored_customer_id: true,
      log_dir_name: undefined,
    };
  },
  computed: {
    ...mapState("settings", ["user_accounts", "active_user_index", "allow_sw_update_install"]),
  },
  watch: {
    allow_sw_update_install: function () {
      ipcRenderer.send("set_sw_update_auto_install", this.allow_sw_update_install);
    },
  },
  created: async function () {
    ipcRenderer.on("logs_flask_dir_response", (e, log_dir_name) => {
      this.$store.commit("settings/set_log_path", log_dir_name);
      this.log_dir_name = log_dir_name;
      const filename_prefix = path.basename(log_dir_name);

      // Only way to create a custom file path for the renderer process logs
      log.transports.file.resolvePath = () => {
        const filename = filename_prefix + "_renderer.txt";
        return path.join(this.log_dir_name, filename);
      };

      console.log = log.log;
      console.error = log.error;
      console.log("Initial view has been rendered"); // allow-log
    });

    if (this.log_dir_name === undefined) {
      ipcRenderer.send("logs_flask_dir_request");
    }

    // init store values needed in pages here since this side bar is only created once
    this.$store.commit("data/set_heatmap_values", {
      "Twitch Force": { data: [...Array(24)].map((_) => Array(0)) },
      "Twitch Frequency": { data: [...Array(24)].map((_) => Array(0)) },
    });

    this.$store.commit("waveform/set_x_axis_zoom_idx", 2);
    this.$store.commit("waveform/set_x_axis_zoom_levels", [
      { x_scale: 30 * 1e6 },
      { x_scale: 15 * 1e6 },
      { x_scale: 5 * 1e6 },
      { x_scale: 2 * 1e6 },
      { x_scale: 1 * 1e6 },
    ]);
    this.$store.dispatch("flask/start_status_pinging");

    ipcRenderer.on("confirmation_request", () => {
      this.confirmation_request = true;
    });

    ipcRenderer.on("beta_2_mode_response", (_, beta_2_mode) => {
      this.beta_2_mode = beta_2_mode;
      this.$store.commit("settings/set_beta_2_mode", beta_2_mode);
    });
    ipcRenderer.on("stored_customer_id_response", (_, stored_customer_id) => {
      this.request_stored_customer_id = false;
      this.$store.commit("settings/set_stored_customer_id", stored_customer_id);
    });

    if (this.beta_2_mode === undefined) {
      ipcRenderer.send("beta_2_mode_request");
    }
    if (this.request_stored_customer_id) {
      ipcRenderer.send("stored_customer_id_request");
    }
  },
  methods: {
    send_confirmation: function (idx) {
      ipcRenderer.send("confirmation_response", idx);
      this.confirmation_request = false;
    },
    save_customer_id: function () {
      const customer_id = this.user_accounts[this.active_user_index].customer_id;
      ipcRenderer.send("save_customer_id", customer_id);
      this.$store.commit("settings/set_stored_customer_id", customer_id);
    },
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
  width: 1629px;
}
.div__recording-status-container {
  float: right;
  position: relative;
  height: 45px;
  width: 650px;
  display: flex;
  justify-content: space-between;
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
.div__stim-barcode-container {
  position: absolute;
  top: 420px;
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
  top: 300px;
  left: 0px;
}

.div__stimulation_controls-controls-icon-container {
  position: absolute;
  top: 505px;
  left: 0px;
}
.div__stim-studio-screen-view {
  position: absolute;
  top: 32px;
  left: 7px;
  width: 44px;
  height: 44px;
  opacity: 0;
}

.div__screen-view-container {
  position: absolute;
  width: 287px;
  display: grid;
  grid-template-columns: 50% 50%;
  justify-items: center;
}
.div__screen-view-container--beta-2-mode {
  top: 635px;
}
.div__screen-view-container--beta-1-mode {
  top: 410px;
}
.span__screen-view-options-text {
  line-height: 100%;
  position: absolute;
  width: 207px;
  height: 23px;
  left: 11px;
  padding: 5px;
  user-select: none;
  font-size: 16px;
  color: #ffffff;
  text-align: left;
}
.span__screen-view-options-text--beta-2-mode {
  top: 605px;
}
.span__screen-view-options-text--beta-1-mode {
  top: 376px;
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
