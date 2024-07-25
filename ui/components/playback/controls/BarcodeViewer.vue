<template>
  <div class="div__plate-barcode" :style="dynamic_container_style">
    <span
      v-b-popover.hover.top="edit_barcode_tooltip_text"
      class="span__plate-barcode-text"
      :style="dynamic_label_style"
    >
      {{ barcode_label }}:
    </span>
    <input
      id="plateinfo"
      :disabled="is_disabled"
      type="text"
      spellcheck="false"
      class="input__plate-barcode-entry"
      :style="dynamic_entry_style"
      :class="[
        barcode_info.valid ? `input__plate-barcode-entry-valid` : `input__plate-barcode-entry-invalid`,
      ]"
      :value="barcode_info.value"
      @input="handle_manual_barcode_input"
    />
    <div
      v-if="barcode_manual_mode && active_processes"
      v-b-popover.hover.top="tooltip_text"
      :title="barcode_label"
      class="div__disabled-input-popover"
    />
    <div
      v-b-popover.hover.top="switch_mode_tooltip_text"
      :title="barcode_label"
      class="input__plate-barcode-manual-entry-enable"
    >
      <span class="input__plate-barcode-manual-entry-enable-icon">
        <div id="edit-plate-barcode" @click="active_processes || $bvModal.show('edit-plate-barcode-modal')">
          <FontAwesomeIcon :icon="['fa', barcode_manual_mode ? 'hdd' : 'pencil-alt']" />
        </div>
      </span>
    </div>
    <div v-if="barcode_type == 'plate_barcode'" class="div__barcode-description">
      {{ barcode_description }}
    </div>
    <b-modal id="edit-plate-barcode-modal" size="sm" hide-footer hide-header hide-header-close>
      <StatusWarningWidget
        :modal_labels="barcode_mode_switch_labels"
        @handle_confirmation="handle_manual_mode_choice"
      />
    </b-modal>
    <b-modal id="barcode-warning" size="sm" hide-footer hide-header hide-header-close>
      <StatusWarningWidget
        :modal_labels="barcode_warning_labels"
        @handle_confirmation="close_warning_modal"
      />
    </b-modal>
  </div>
</template>
<script>
import { mapState } from "vuex";
import playback_module from "@/store/modules/playback";
import { library } from "@fortawesome/fontawesome-svg-core";
import { faPencilAlt, faHdd } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import StatusWarningWidget from "@/components/status/StatusWarningWidget.vue";
import Vue from "vue";
import { VBPopover } from "bootstrap-vue";
Vue.directive("b-popover", VBPopover);

const get_dur_since = (now, then) => {
  now = now.getTime();
  then = then.getTime();
  const diff_secs = Math.floor((now - then) / 1000);
  return `${Math.floor(diff_secs / 3600)}H ${Math.floor(diff_secs / 60) % 60}M ${diff_secs % 60}s`;
};

library.add(faPencilAlt);
library.add(faHdd);
/**
 * @vue-data {String} playback_state_enums - Current state of playback
 * @vue-computed {String} playback_state - Current value in Vuex store
 * @vue-event {String} set_barcode_manually - User entered String parser
 */
export default {
  name: "BarcodeViewer",
  components: {
    FontAwesomeIcon,
    StatusWarningWidget,
  },
  props: {
    barcode_type: { type: String, default: "plate_barcode" },
  },
  data() {
    return {
      playback_state_enums: playback_module.ENUMS.PLAYBACK_STATES,
      barcode_automatic_labels: {
        header: "Warning!",
        msg_one: "Do you want to switch to automatic barcode scanning?",
        msg_two:
          "This will disable manual barcode editing and clear the current barcodes until the next automatic barcode scan.",
        button_names: ["Cancel", "Yes"],
      },
      barcode_manual_labels: {
        header: "Warning!",
        msg_one: "Do you want to switch to manual barcode editing?",
        msg_two: "While active, all barcodes must be entered manually. Scanned barcodes will be ignored.",
        button_names: ["Cancel", "Yes"],
      },
      barcode_warning_labels: {
        header: "Warning!",
        msg_one: "A new barcode has been detected while a process was active.",
        msg_two: "All processes have been stopped.",
        button_names: ["Okay"],
      },
      now_time: null,
      now_time_interval: null,
    };
  },
  computed: {
    ...mapState("playback", ["playback_state", "barcodes", "barcode_warning"]),
    ...mapState("flask", ["barcode_manual_mode"]),
    ...mapState("stimulation", ["stim_play_state"]),
    barcode_info: function () {
      return this.barcodes[this.barcode_type];
    },
    barcode_entry_time: function () {
      return this.barcode_info.entry_time;
    },
    barcode_label: function () {
      return this.barcode_type == "plate_barcode" ? "Plate Barcode" : "Stim Lid Barcode";
    },
    barcode_description: function () {
      if (this.barcode_info.valid) {
        const experiment_id = parseInt(this.barcode_info.value.split("-")[0].slice(-3));
        if (experiment_id <= 99) {
          return "Cardiac (1x)";
        } else if (experiment_id <= 199) {
          return "SkM (12x)";
        } else if (experiment_id <= 299) {
          return "Variable";
        } else if (experiment_id <= 399) {
          return "Mini Cardiac (1x)";
        } else if (experiment_id <= 499) {
          return "Mini SkM (12x)";
        } else {
          return "Cardiac (1x)";
        }
      } else {
        return "Invalid";
      }
    },
    barcode_mode_switch_labels: function () {
      return this.barcode_manual_mode ? this.barcode_automatic_labels : this.barcode_manual_labels;
    },
    dynamic_container_style: function () {
      return this.barcode_type == "plate_barcode" ? "height: 46px;" : "height: 34px;";
    },
    dynamic_label_style: function () {
      return this.barcode_type == "plate_barcode" ? "left: 17px;" : "left: 0px;";
    },
    dynamic_entry_style: function () {
      return this.barcode_type == "plate_barcode" ? "width: 110px;" : "width: 105px;";
    },
    edit_barcode_tooltip_text: function () {
      let msg = "";
      if (this.barcode_entry_time !== null && this.barcode_info.value && this.now_time !== null) {
        const prefix = this.barcode_manual_mode ? "Manually entered" : "Scanned";

        msg += `${prefix} ${get_dur_since(this.now_time, this.barcode_entry_time)} ago. `;
      }
      if (this.barcode_manual_mode) {
        if (this.is_data_streaming) {
          if (this.playback_state === this.playback_state_enums.CALIBRATING) {
            msg += "Cannot edit barcodes while calibrating.";
          } else {
            msg += "Cannot edit barcodes while live view is active.";
          }
        } else if (this.stim_play_state) {
          msg += "Cannot edit barcodes while stimulation is running.";
        }
      }
      return msg;
    },
    switch_mode_tooltip_text: function () {
      if (this.is_data_streaming) {
        if (this.playback_state === this.playback_state_enums.CALIBRATING) {
          return "Cannot switch barcode entry mode while calibrating.";
        }
        return "Cannot switch barcode entry mode while live view is active.";
      } else if (this.stim_play_state) {
        return "Cannot switch barcode entry mode while stimulation is running.";
      }
      return this.barcode_manual_mode ? "Enter automatic mode" : "Enter manual mode";
    },
    is_data_streaming: function () {
      return (
        this.playback_state === this.playback_state_enums.RECORDING ||
        this.playback_state === this.playback_state_enums.BUFFERING ||
        this.playback_state === this.playback_state_enums.LIVE_VIEW_ACTIVE ||
        this.playback_state === this.playback_state_enums.CALIBRATING
      );
    },
    active_processes: function () {
      return this.stim_play_state || this.is_data_streaming;
    },
    is_disabled: function () {
      return this.active_processes || !this.barcode_manual_mode;
    },
  },
  watch: {
    barcode_entry_time: function () {
      if (this.now_time_interval) {
        clearInterval(this.now_time_interval);
      }
      this.now_time = this.barcode_entry_time;
      this.now_time_interval = setInterval(this.update_now, 1000);
    },
    barcode_warning: function () {
      if (this.barcode_warning) {
        this.$bvModal.show("barcode-warning");
      }
    },
  },
  methods: {
    handle_manual_mode_choice(switched) {
      switched = Boolean(switched);
      this.$bvModal.hide("edit-plate-barcode-modal");
      if (!switched) {
        return;
      }
      const new_barcode_manual_mode = !this.barcode_manual_mode;
      this.$store.commit("flask/set_barcode_manual_mode", new_barcode_manual_mode);
      if (new_barcode_manual_mode) {
        console.log("Barcode entry mode set to manual"); // allow-log
      } else {
        console.log("Barcode entry mode set to automatic, clearing barcodes"); // allow-log
        this.set_barcode_manually("plate_barcode", "");
        this.set_barcode_manually("stim_barcode", "");
      }
    },
    handle_manual_barcode_input: function (event) {
      this.$store.commit("playback/set_barcode_entry_time", this.barcode_type);
      this.set_barcode_manually(this.barcode_type, event.target.value);
    },
    set_barcode_manually: function (barcode_type, new_barcode) {
      this.$store.dispatch("playback/validate_barcode", {
        type: barcode_type,
        new_value: new_barcode,
      });
    },
    close_warning_modal() {
      this.$bvModal.hide("barcode-warning");
      this.$store.commit("playback/set_barcode_warning", false);
    },
    update_now() {
      this.now_time = new Date();
    },
  },
};
</script>
<style>
.div__plate-barcode *,
.div__plate-barcode *:before,
.div__plate-barcode *:after {
  -webkit-box-sizing: content-box;
  -moz-box-sizing: content-box;
  box-sizing: content-box;
}

.div__plate-barcode {
  position: relative;
  top: 0px;
  left: 0px;
  width: 287px;
  background: #1c1c1c;
  -webkit-box-sizing: content-box;
  box-sizing: content-box;
}

.div__barcode-description {
  position: absolute;
  top: 32px;
  color: #cccc;
  left: 138px;
  font-size: 12px;
}

.span__plate-barcode-text {
  pointer-events: all;
  line-height: 100%;
  overflow: hidden;
  position: absolute;
  width: 278px;
  height: 23px;
  top: 2px;
  padding: 5px;
  user-select: none;
  font-family: "Muli";
  font-weight: normal;
  font-style: normal;
  text-decoration: none;
  font-size: 16px;
  color: rgb(255, 255, 255);
  text-align: left;
}

.input__plate-barcode-entry *,
.input__plate-barcode-entry *:before,
.input__plate-barcode-entry *:after {
  -webkit-box-sizing: content-box;
  -moz-box-sizing: content-box;
  box-sizing: content-box;
}

.input__plate-barcode-entry {
  padding-left: 5px;
  padding-right: 5px;
  overflow: hidden;
  white-space: nowrap;
  text-align: left;
  line-height: 24px;
  font-style: normal;
  text-decoration: none;
  font-size: 15px;
  background-color: #000000;
  color: #b7b7b7;
  font-family: anonymous pro;
  font-weight: normal;
  box-shadow: none;
  border: none;
  position: absolute;
  height: 24px;
  top: 3px;
  right: 27px;
}

.div__disabled-input-popover {
  position: absolute;
  height: 24px;
  width: 100px;
  top: 3px;
  right: 27px;
}

.input__plate-barcode-entry-invalid {
  border: 1px solid red;
}

.input__plate-barcode-entry-valid {
  border: 1px solid green;
}
input:focus {
  outline: none;
}

.input__plate-barcode-manual-entry-enable {
  pointer-events: all;
  position: absolute;
  width: 34px;
  height: 34px;
  top: 0px;
  left: 263px;
}

.input__plate-barcode-manual-entry-enable-icon {
  overflow: hidden;
  white-space: nowrap;
  text-align: center;
  font-weight: normal;
  transform: translateZ(0px);
  position: absolute;
  width: 24px;
  height: 24px;
  line-height: 24px;
  top: 5px;
  left: 0px;
  font-size: 14px;
  color: #b7b7b7;
}

.fa-pencil-alt:hover {
  color: #ececed;
}

.modal-backdrop {
  background-color: rgb(0, 0, 0, 0.5);
}

/* Center these modal pop-up dialogs within the viewport */
#barcode-warning,
#edit-plate-barcode-modal {
  position: fixed;
  margin: 5% auto;
  top: 15%;
  left: 0;
  right: 0;
}
</style>
