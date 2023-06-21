<template>
  <div>
    <div class="div__sidebar">
      <div class="div__sidebar-page-divider" />
      <div class="div__component-container">
        <div class="div__plate-barcode-container">
          <BarcodeViewer />
        </div>
        <div class="div__stim-barcode-container">
          <BarcodeViewer :barcodeType="'stimBarcode'" />
        </div>
        <div class="div__stim-status-container">
          <StatusBar :stimSpecific="true" @send-confirmation="sendConfirmation" />
        </div>
        <div class="div__stimulation-controls-icon-container">
          <StimulationStudioControls @save-account-info="saveAccountInfo" />
        </div>
        <div class="div__simulation-mode-container">
          <SimulationMode />
        </div>
        <span class="span__copyright"
          >&copy;{{ currentYear }} Curi Bio. All Rights Reserved. Version:
          {{ packageVersion }}
        </span>
      </div>
    </div>
    <div class="div__top-header-bar" />
    <div class="div__nuxt-page">
      <nuxt />
    </div>
  </div>
</template>
<script>
import Vue from "vue";

import { BarcodeViewer, StatusBar, SimulationMode, StimulationStudioControls } from "@curi-bio/ui";

import { mapState } from "vuex";
import { VBPopover, VBToggle } from "bootstrap-vue";
import { ipcRenderer } from "electron";
import path from "path";

const log = require("electron-log");
// Note: Vue automatically prefixes the directive name with 'v-'
Vue.directive("b-popover", VBPopover);
Vue.directive("b-toggle", VBToggle);

export default {
  components: {
    BarcodeViewer,
    StatusBar,
    SimulationMode,
    StimulationStudioControls,
  },
  data: function () {
    return {
      packageVersion: "",
      latestSwVersionAvailable: null,
      logDirName: null,
      requestStoredAccounts: true,
      currentYear: "2023", // TODO look into better ways of handling this. Not sure if just using the system's current year is the best approach
    };
  },
  computed: {
    ...mapState("stimulation", ["stimPlayState"]),
    ...mapState("system", ["statusUuid", "allowSwUpdateInstall", "isConnectedToController"]),
    ...mapState("settings", ["userAccount"]),
  },
  watch: {
    allowSwUpdateInstall: function () {
      ipcRenderer.send("setSwUpdateAutoInstall", this.allowSwUpdateInstall);
    },
    latestSwVersionAvailable: function () {
      this.setLatestSwVersion();
    },
    isConnectedToController: function () {
      this.setLatestSwVersion();
    },
  },

  created: async function () {
    ipcRenderer.on("logsFlaskDirResponse", (e, logDirName) => {
      this.$store.commit("settings/setLogPath", logDirName);
      this.logDirName = logDirName;
      const filenamePrefix = path.basename(logDirName);

      // Only way to create a custom file path for the renderer process logs
      log.transports.file.resolvePath = () => {
        const filename = filenamePrefix + "_renderer.txt";
        return path.join(this.logDirName, filename);
      };
      // set to UTC, not local time
      process.env.TZ = "UTC";
      console.log = log.log;
      console.error = log.error;
      console.log("Initial view has been rendered"); // allow-log
    });

    if (this.logDirName === null) {
      ipcRenderer.send("logsFlaskDirRequest");
    }

    // the version of the running (current) software is stored in the main process of electron, so request it to be sent over to this process
    ipcRenderer.on("swVersionResponse", (_, packageVersion) => {
      this.packageVersion = packageVersion;
    });
    if (this.packageVersion === "") {
      ipcRenderer.send("swVersionRequest");
    }

    // the electron auto-updater runs in the main process of electron, so request it to be sent over to this process
    ipcRenderer.on("latestSwVersionResponse", (_, latestSwVersionAvailable) => {
      this.latestSwVersionAvailable = latestSwVersionAvailable;
    });
    if (this.latestSwVersionAvailable === null) {
      ipcRenderer.send("latestSwVersionRequest");
    }

    ipcRenderer.on("confirmationRequest", () => {
      this.$store.commit("system/setConfirmationRequest", true);
    });

    ipcRenderer.on("storedAccountsResponse", (_, storedAccounts) => {
      // storedAccounts will contain both customerId and usernames
      this.requestStoredAccounts = false;
      this.storedAccounts = storedAccounts;
      this.$store.commit("settings/setStoredAccounts", storedAccounts);
    });

    if (this.requestStoredAccounts) {
      ipcRenderer.send("storedAccountsRequest");
    }
  },
  methods: {
    sendConfirmation: function (idx) {
      ipcRenderer.send("confirmationResponse", idx);
      this.$store.commit("system/setConfirmationRequest", false);
    },
    setLatestSwVersion: function () {
      if (this.latestSwVersionAvailable && this.isConnectedToController) {
        this.$store.dispatch("system/sendSetLatestSwVersion", this.latestSwVersionAvailable);
      }
    },
    saveAccountInfo: function () {
      // this gets called before any vuex actions/muts to store account details so logic to username is in electron main process
      const { customerId, username } = this.userAccount;

      ipcRenderer.invoke("saveAccountInfoRequest", { customerId, username }).then((response) => {
        this.$store.commit("settings/setStoredAccounts", response);
      });
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
.div__component-container {
  top: 45px;
  position: absolute;
  width: 287px;
}

/* NON-SPECIFIC */
.div__top-header-bar {
  position: absolute;
  left: 289px;
  background-color: #111111;
  height: 45px;
  width: 1629px;
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
.div__plate-barcode-container {
  position: relative;
  left: 0px;
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

.div__stimulation-controls-icon-container {
  position: relative;
  margin-top: 3px;
  left: 0px;
  overflow: hidden;
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
</style>
