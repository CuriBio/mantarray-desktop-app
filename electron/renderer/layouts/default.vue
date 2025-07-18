<template>
  <div>
    <div class="div__sidebar">
      <div class="div__sidebar-page-divider" />
      <div class="div__accordian-container" role="tablist">
        <NuxtLink to="/">
          <div
            role="tab"
            @click="handle_tab_visibility(0)"
            @mouseenter="data_acquisition_hover = true"
            @mouseleave="data_acquisition_hover = false"
          >
            <div
              v-b-toggle.data-acquisition-card
              class="div__accordian-tabs"
              :class="data_acquisition_dynamic_class"
            >
              Data Acquisition
              <div
                class="div__arrow"
                :class="{ expanded: data_acquisition_visibility }"
                :style="data_acquisition_hover ? 'border-top: 6px solid #000' : null"
              />
            </div>
          </div>
        </NuxtLink>
        <b-collapse
          v-model="data_acquisition_visibility"
          visible
          accordion="controls-accordion"
          role="tabpanel"
        >
          <div class="div__plate-barcode-container">
            <BarcodeViewer />
          </div>
          <div class="div__plate-navigator-container">
            <PlateNavigator />
          </div>
          <NuxtLink to="/platemapeditor">
            <PlateMapEditorButton />
          </NuxtLink>
          <div class="div__status-bar-container">
            <StatusBar
              :da_check="da_check"
              @close_da_check_modal="close_da_check_modal"
              @send_confirmation="send_confirmation"
            />
          </div>
          <div class="div__player-controls-container">
            <DesktopPlayerControls @save_account_info="save_account_info" />
          </div>
          <div class="div__screen-view-options-text">Screen View Options</div>
          <div class="div__screen-view-container">
            <div class="div__waveform-screen-view">
              <!-- Default view is waveform screen -->
              <NuxtLink to="/">
                <img
                  v-b-popover.hover.bottom="'Click to view'"
                  :title="'Contraction Trace Live View'"
                  src="../assets/img/waveform-screen-view.png"
                />
              </NuxtLink>
            </div>
            <div class="div__heatmap-screen-view">
              <NuxtLink to="/heatmap">
                <img
                  v-b-popover.hover.bottom="'Click to view'"
                  :title="'Heat Map Live View'"
                  src="../assets/img/heatmap-screen-view.png"
                />
              </NuxtLink>
            </div>
          </div>
        </b-collapse>
        <NuxtLink to="/stimulationstudio">
          <div
            v-if="beta_2_mode"
            role="tab"
            @click="handle_tab_visibility(1)"
            @mouseenter="stim_studio_hover = true"
            @mouseleave="stim_studio_hover = false"
          >
            <div v-b-toggle.stim-studio-card class="div__accordian-tabs" :class="stim_studio_dynamic_class">
              Stimulation Studio
              <div
                class="div__arrow"
                :class="{ expanded: stim_studio_visibility }"
                :style="stim_studio_hover ? 'border-top: 6px solid #000' : null"
              />
            </div>
          </div>
        </NuxtLink>
        <b-collapse v-model="stim_studio_visibility" accordion="controls-accordion" role="tabpanel">
          <div class="div__stim-barcode-container">
            <BarcodeViewer :barcode_type="'stim_barcode'" />
          </div>
          <div class="div__stim-status-container">
            <StatusBar :stim_specific="true" @send_confirmation="send_confirmation" />
          </div>
          <div class="div__stimulation_controls-controls-icon-container">
            <StimulationControls />
          </div>
        </b-collapse>
        <div
          v-if="beta_2_mode"
          role="tab"
          @click="da_check = true"
          @mouseenter="data_analysis_hover = true"
          @mouseleave="data_analysis_hover = false"
        >
          <div class="div__accordian-tabs" :class="data_analysis_dynamic_class">
            Data Analysis
            <div
              class="div__arrow"
              :class="{ expanded: data_analysis_visibility }"
              :style="data_analysis_hover ? 'border-top: 6px solid #000' : null"
            />
          </div>
        </div>
        <b-collapse
          id="data-analysis-card"
          v-model="data_analysis_visibility"
          accordion="controls-accordion"
          role="tabpanel"
        >
          <DataAnalysisControl @send_confirmation="send_confirmation" />
        </b-collapse>
      </div>
      <span class="span__changelog-text" :style="changelog_text_dynamic_top" @click="open_changelog"
        >View Changelog</span
      >
      <div class="div__simulation-mode-container">
        <SimulationMode />
      </div>
      <span class="span__copyright"
        >&copy;{{ current_year }} Curi Bio. All Rights Reserved. Version:
        {{ package_version }}
      </span>
    </div>
    <div class="div__top-bar-above-waveforms">
      <StimulationRunningWidget />
      <div class="div__recording-top-bar-container">
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
  DataAnalysisControl,
  PlateMapEditorButton,
  StimulationRunningWidget,
} from "@curi-bio/ui";
import { ipcRenderer } from "electron";
import { mapState } from "vuex";
const log = require("electron-log");
const shell = require("electron").shell;

import path from "path";
import Vue from "vue";

import { VBPopover, VBToggle, BCollapse } from "bootstrap-vue";
// Note: Vue automatically prefixes the directive name with 'v-'
Vue.directive("b-popover", VBPopover);
Vue.directive("b-toggle", VBToggle);

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
    DataAnalysisControl,
    BCollapse,
    StimulationRunningWidget,
    PlateMapEditorButton,
  },
  data: function () {
    return {
      package_version: "",
      current_year: "2025", // TODO look into better ways of handling this. Not sure if just using the system's current year is the best approach
      beta_2_mode: process.env.SPECTRON || undefined,
      pulse3d_version_info: undefined,
      log_dir_name: undefined,
      data_acquisition_visibility: true,
      stim_studio_visibility: false,
      data_analysis_visibility: false,
      data_analysis_hover: false,
      data_acquisition_hover: false,
      stim_studio_hover: false,
      request_stored_accounts: true,
      da_check: false,
      stored_accounts: {},
    };
  },
  computed: {
    ...mapState("settings", [
      "user_account",
      "allow_sw_update_install",
      "recordings_list",
      "root_recording_path",
      "new_recording_path",
      "choosing_recording_dir",
    ]),

    ...mapState("playback", ["data_analysis_state", "playback_state", "start_recording_from_stim"]),
    ...mapState("stimulation", ["stim_play_state"]),
    ...mapState("flask", ["status_uuid", "log_file_id", "simulation_mode"]),
    data_acquisition_dynamic_class: function () {
      return this.data_acquisition_visibility ? "div__accordian-tabs-visible" : "div__accordian-tabs";
    },
    stim_studio_dynamic_class: function () {
      return this.stim_studio_visibility ? "div__accordian-tabs-visible" : "div__accordian-tabs";
    },
    data_analysis_dynamic_class: function () {
      return this.data_analysis_visibility ? "div__accordian-tabs-visible" : "div__accordian-tabs";
    },
    changelog_text_dynamic_top: function () {
      return this.simulation_mode ? "top: 850px" : "top: 885px";
    },
  },
  watch: {
    allow_sw_update_install: function () {
      ipcRenderer.send("set_sw_update_auto_install", this.allow_sw_update_install);
    },
    start_recording_from_stim(start_rec) {
      // start recording if set to true
      if (start_rec) {
        // if recording has been started from stim studio, redirect to live view page
        this.$router.push({ path: "/" });
        this.handle_tab_visibility(0);
      }
    },
    choosing_recording_dir(choosing) {
      if (choosing) {
        ipcRenderer.send("open_file_picker", {
          file_type: "recording_dir",
          current_file: this.new_recording_path || this.root_recording_path,
        });
      }
    },
  },
  created: async function () {
    ipcRenderer.on("logs_flask_dir_response", (e, info) => {
      const { log_dir_name, recording_dir_name } = info;
      this.$store.commit("settings/set_root_recording_dir", recording_dir_name);

      this.$store.commit("settings/set_log_path", log_dir_name);
      this.log_dir_name = log_dir_name;
      const filename_prefix = path.basename(log_dir_name);

      // Only way to create a custom file path for the renderer process logs
      log.transports.file.resolvePath = () => {
        const filename = filename_prefix + "_renderer.txt";
        return path.join(this.log_dir_name, filename);
      };
      // set to UTC, not local time
      process.env.TZ = "UTC";
      console.log = log.log;
      console.error = log.error;
      console.log("Initial view has been rendered"); // allow-log
    });
    if (this.log_dir_name === undefined) {
      ipcRenderer.send("logs_flask_dir_request");
    }

    ipcRenderer.on("log_file_id_response", (e, log_file_id) => {
      this.$store.commit("flask/set_log_file_id", log_file_id);
    });
    if (!this.log_file_id) {
      ipcRenderer.send("log_file_id_request");
    }

    ipcRenderer.on("sw_version_response", (_, package_version) => {
      this.package_version = package_version;
    });
    if (this.package_version === "") {
      ipcRenderer.send("sw_version_request");
    }

    // init store values needed in pages here since this side bar is only created once
    this.$store.commit("data/set_heatmap_values", {
      "Twitch Frequency": { data: [...Array(24)].map((_) => Array(0)) },
      "Twitch Force": { data: [...Array(24)].map((_) => Array(0)) },
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
      this.$store.commit("settings/set_confirmation_request", true);
    });

    ipcRenderer.on("pulse3d_versions_response", (_, pulse3d_version_info) => {
      this.pulse3d_version_info = pulse3d_version_info;
      if (pulse3d_version_info) {
        // only update values if versions were actually retrieved
        this.$store.commit("settings/set_pulse3d_version_info", pulse3d_version_info);
      }
    });
    if (this.pulse3d_version_info === undefined) {
      ipcRenderer.send("pulse3d_versions_request");
    }

    ipcRenderer.on("beta_2_mode_response", (_, beta_2_mode) => {
      this.beta_2_mode = beta_2_mode;
      this.$store.commit("settings/set_beta_2_mode", beta_2_mode);
    });
    if (this.beta_2_mode === undefined) {
      ipcRenderer.send("beta_2_mode_request");
    }

    ipcRenderer.on("stored_accounts_response", (_, stored_accounts) => {
      // stored_accounts will contain both customer_id and usernames
      this.request_stored_accounts = false;
      this.stored_accounts = stored_accounts;
      this.$store.commit("settings/set_stored_accounts", stored_accounts);
    });
    if (this.request_stored_accounts) {
      ipcRenderer.send("stored_accounts_request");
    }

    ipcRenderer.on("file_picked", (_, res) => {
      if (res.file_type === "recording_dir") {
        this.$store.commit("settings/set_choosing_recording_dir", false);
        if (res.new_file) {
          this.$store.commit("settings/set_new_recording_dir", res.new_file);
        }
      }
    });
  },
  methods: {
    send_confirmation: function (idx) {
      ipcRenderer.send("confirmation_response", idx);
      this.$store.commit("settings/set_confirmation_request", false);
    },
    save_account_info: function () {
      // this gets called before any vuex actions/muts to store account details so logic to username is in electron main process
      const { customer_id, username } = this.user_account;

      ipcRenderer.invoke("save_account_info", { customer_id, username }).then((response) => {
        this.$store.commit("settings/set_stored_accounts", response);
      });
    },
    handle_tab_visibility: function (tab) {
      this.data_acquisition_visibility = tab === 0 && !this.data_acquisition_visibility;
      this.stim_studio_visibility = tab === 1 && !this.stim_studio_visibility;
      this.data_analysis_visibility = tab === 2 && !this.data_analysis_visibility;
    },
    close_da_check_modal: function (idx) {
      if (idx === 1) this.handle_tab_visibility(2);
      this.da_check = false;
    },
    open_changelog: function () {
      shell.openExternal("https://github.com/CuriBio/mantarray-desktop-app/blob/main/CHANGELOG.rst");
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

/* ACCORDIAN*/
#stim-studio-card {
  padding-bottom: 10px;
  width: 390px;
}

#data-acquisition-card {
  padding: 5px 0px 10px 0px;
}

.div__accordian-container {
  top: 45px;
  position: absolute;
  width: 287px;
}

.div__accordian-tabs {
  background-color: #000;
  color: #b7b7b7;
  font-family: Muli;
  width: 287px;
  height: 40px;
  border-top: 2px solid #1c1c1c;
  border-bottom: 2px solid #1c1c1c;
  border-left: 1px solid #000;
  border-right: 1px solid #000;
  text-align: left;
  padding-top: 5px;
  padding-left: 15px;
}

.div__accordian-tabs:hover,
.div__accordian-tabs-visible:hover {
  background-color: #b7b7b7c9;
  color: #000;
}

.div__accordian-tabs-visible {
  background-color: #b7b7b7;
  color: #000;
}

/* NON-SPECIFIC */
.div__arrow {
  position: relative;
  top: -13px;
  left: 245px;
  border-left: 4px solid transparent;
  border-right: 4px solid transparent;
  border-top: 6px solid #b7b7b7c9;
  width: 9px;
  transform: rotateZ(0deg) translateY(0px);
  transition-duration: 0.3s;
  transition-timing-function: cubic-bezier(0.59, 1.39, 0.37, 1.01);
}

.expanded {
  transform: rotateZ(180deg) translateY(2px);
  border-top: 6px solid #000;
}

.arrow_hover {
  border-top: 6px solid #000;
}

.div__top-bar-above-waveforms {
  position: absolute;
  left: 289px;
  background-color: #111111;
  height: 45px;
  width: 1629px;
  display: flex;
  justify-content: flex-end;
  align-items: center;
}

.div__recording-top-bar-container {
  float: right;
  position: relative;
  height: 45px;
  width: 650px;
  display: flex;
  justify-content: space-between;
  text-align: left;
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

/* DATA-ACQUISITION */
.div__screen-view-container {
  position: relative;
  width: 287px;
  display: grid;
  grid-template-columns: 50% 50%;
  justify-items: center;
}

.div__plate-barcode-container {
  position: relative;
  left: 0px;
}

.div__status-bar-container {
  position: relative;
  left: 0px;
}

.div__plate-navigator-container {
  position: relative;
  top: 5px;
  left: 0px;
}

.div__screen-view-options-text {
  line-height: 100%;
  position: relative;
  width: 207px;
  height: 23px;
  left: 11px;
  padding: 5px;
  user-select: none;
  font-size: 16px;
  color: #ffffff;
  text-align: left;
  margin: 10px;
}

.div__waveform-screen-view- {
  grid-column: 1 / 2;
}

.div__heatmap-screen-view- {
  grid-column: 2;
}

.div__player-controls-container {
  position: relative;
  left: 0px;
  margin: 5px 0;
}

/* STIM STUDIO */
.div__stim-status-container {
  position: relative;
  margin-top: 8px;
}

.div__stim-barcode-container {
  position: relative;
  left: 0px;
  margin-top: 10px;
}

.div__stimulation_controls-controls-icon-container {
  position: relative;
  margin-top: 3px;
  left: 0px;
  overflow: hidden;
}

.div__stim-studio-screen-view {
  position: absolute;
  top: 32px;
  left: 7px;
  width: 44px;
  height: 44px;
  opacity: 0;
}

/* STIMULATION/COPYRIGHT */
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

.span__changelog-text {
  position: absolute;
  z-index: 99;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
  box-sizing: border-box;
  line-height: 100%;
  overflow: hidden;
  width: 286px;
  height: 20px;
  left: -0.252101px;
  padding: 5px;
  user-select: none;
  font-family: Muli;
  font-weight: normal;
  font-style: normal;
  text-decoration: none;
  font-size: 11px;
  color: #ffffff;
  text-align: center;
}
.span__changelog-text:hover {
  cursor: pointer;
  color: rgb(27, 158, 119);
}
</style>
