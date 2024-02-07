<template>
  <div>
    <div class="div__recording-name-input-background">
      <div class="div__outer_container">
        <span class="span__recording-name-input-label">{{ modal_labels.header }}</span>
        <div id="recording_name" class="div__recording-name-input-box">
          <InputWidget
            :title_label="modal_labels.msg"
            :placeholder="'Recording File Name'"
            :invalid_text="recording_name_error_message"
            :spellcheck="false"
            :input_width="400"
            :dom_id_suffix="'recording-name'"
            :initial_value="default_recording_name"
            @update:value="check_recording_name($event)"
          />
        </div>
        <div class="div__metadata_container">
          <div class="div__metadata_title">
            <span class="span__metadata_label"
              >Optionally, add additional metadata to save in the recording:</span
            >
            <div class="div__metadata-add-remove-container">
              <span class="span__axis-controls-add-remove-kv-button" @click="remove_metadata_kv(-1)">
                <FontAwesomeIcon :icon="['fa', 'minus-circle']" />
              </span>
              <span class="span__axis-controls-add-remove-kv-button" @click="add_metadata_kv">
                <FontAwesomeIcon :icon="['fa', 'plus-circle']" />
              </span>
            </div>
          </div>
          <div class="div__metadata-backdrop">
            <div
              v-for="i of Array(user_defined_metadata.length).keys()"
              :key="`key-value-entry-${i}`"
              class="div__metadata-row"
            >
              <span class="span__metadata_row_label">Key:</span>
              <div class="div__metadata_input_container">
                <InputWidget
                  :placeholder="'Experiment Name'"
                  :invalid_text="user_defined_metadata[i].key_err"
                  :spellcheck="false"
                  :input_width="210"
                  :dom_id_suffix="`metadata-key-${i}`"
                  :initial_value="user_defined_metadata[i].key"
                  :container_background_color="'#191919'"
                  @update:value="update_metadata(i, 'key', $event)"
                />
              </div>
              <span class="span__metadata_row_label">Value:</span>
              <div class="div__metadata_input_container">
                <InputWidget
                  :placeholder="'Project 1'"
                  :invalid_text="user_defined_metadata[i].val_err"
                  :spellcheck="false"
                  :input_width="210"
                  :dom_id_suffix="`metadata-value-${i}`"
                  :initial_value="user_defined_metadata[i].val"
                  :container_background_color="'#191919'"
                  @update:value="update_metadata(i, 'val', $event)"
                />
              </div>
              <span
                class="span__axis-controls-add-remove-kv-button"
                :style="'padding-top: 14px; padding-left: 20px;'"
                @click="remove_metadata_kv(i)"
              >
                <FontAwesomeIcon :icon="['fa', 'minus-circle']" />
              </span>
            </div>
          </div>
        </div>
        <div v-if="beta_2_mode" class="div__toggle-container">
          <ToggleWidget
            id="run_recording_snapshot_current"
            :checked_state="run_recording_snapshot_current"
            :label="'run_recording_snapshot_current'"
            @handle_toggle_state="handle_snapshot_toggle"
          />
          <span>Show Snapshot For This Recording</span>
        </div>
        <div class="div__confirm-button-container">
          <ButtonWidget
            :button_widget_width="700"
            :button_widget_height="50"
            :button_widget_top="0"
            :button_widget_left="0"
            :button_names="['Confirm']"
            :enabled_color="'#B7B7B7'"
            :is_enabled="[is_enabled]"
            :hover_color="['#19ac8a']"
            @btn-click="handle_click"
          />
        </div>
      </div>
    </div>
    <b-modal
      id="existing-recording-warning"
      size="sm"
      hide-footer
      hide-header
      hide-header-close
      :static="true"
      :no-close-on-backdrop="true"
    >
      <StatusWarningWidget
        :modal_labels="existing_recording_labels"
        @handle_confirmation="close_warning_modal"
      />
    </b-modal>
  </div>
</template>
<script>
import InputWidget from "@/components/basic_widgets/InputWidget.vue";
import ButtonWidget from "@/components/basic_widgets/ButtonWidget.vue";
import Vue from "vue";
import StatusWarningWidget from "@/components/status/StatusWarningWidget.vue";
import ToggleWidget from "@/components/basic_widgets/ToggleWidget.vue";
import { mapState } from "vuex";
import { BModal } from "bootstrap-vue";
import { library } from "@fortawesome/fontawesome-svg-core";
import { faMinusCircle, faPlusCircle } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
library.add(faMinusCircle, faPlusCircle);
Vue.component("BModal", BModal);

const EMPTY_METADATA_ERR_MSG = "Please enter a value";
const DUPLICATE_METADATA_KEY_ERR_MSG = "Duplicate key";

export default {
  name: "RecordingNameInputWidget",
  components: { InputWidget, ButtonWidget, StatusWarningWidget, ToggleWidget, FontAwesomeIcon },
  props: {
    modal_labels: {
      type: Object,
      default() {
        return {
          header: "Important!",
          msg: "Choose a name for this recording.",
        };
      },
    },
    default_recording_name: { type: String, default: "" },
  },
  data: function () {
    return {
      recording_name: this.default_recording_name,
      recording_name_error_message: "",
      existing_recording_labels: {
        header: "Warning!",
        msg_one: "The name you chose already exists.",
        msg_two: "Would you like to replace the existing recording with this one?",
        button_names: ["Cancel", "Yes"],
      },
      run_recording_snapshot_current: true,
      user_defined_metadata: this.get_default_user_defined_metadata(),
    };
  },
  computed: {
    ...mapState("settings", ["run_recording_snapshot_default", "beta_2_mode"]),
    is_enabled: function () {
      return (
        !this.recording_name_error_message &&
        !this.user_defined_metadata.some((meta_info) => meta_info.key_err || meta_info.val_err)
      );
    },
    snapshot_enabled: function () {
      return this.beta_2_mode && this.run_recording_snapshot_current;
    },
  },
  watch: {
    run_recording_snapshot_default: function (new_default) {
      // required because bootstrap modals are always rendered to the page so need a way to change the value as it's changed
      this.run_recording_snapshot_current = new_default;
    },
    default_recording_name: function () {
      // Tanner (9/21/23): whenever this value changes, assume that a new recording has been made and clear the user-defined metadata from the previous recording
      this.user_defined_metadata = this.get_default_user_defined_metadata();
    },
  },
  methods: {
    check_recording_name: function (recording_name) {
      this.recording_name = recording_name;
      this.recording_name_error_message = recording_name ? "" : "Please enter a name";
    },
    handle_click: async function () {
      if (this.is_enabled) {
        await this.handle_recording_rename(this.recording_name === this.default_recording_name);
      }
    },
    close_warning_modal: async function (idx) {
      this.$bvModal.hide("existing-recording-warning");

      if (idx === 1) {
        await this.handle_recording_rename(true);
      } else {
        this.recording_name_error_message = "Name already exists";
      }
    },
    handle_recording_rename: async function (replace_existing) {
      const res = await this.$store.dispatch("playback/handle_recording_rename", {
        recording_name: this.recording_name,
        default_name: this.default_recording_name,
        replace_existing,
        snapshot_enabled: this.snapshot_enabled,
        user_defined_metadata: this.get_formatted_user_defined_metadata(),
      });

      if (res === 403 && !replace_existing) {
        this.$bvModal.show("existing-recording-warning");
      } else {
        this.$emit("handle_confirmation");
        this.$store.commit("playback/set_is_recording_snapshot_running", this.snapshot_enabled);
        // reset this value back to the default
        this.run_recording_snapshot_current = this.beta_2_mode && this.run_recording_snapshot_default;
      }
    },
    get_default_user_defined_metadata: function () {
      return [
        {
          key: "",
          val: "",
          key_err: EMPTY_METADATA_ERR_MSG,
          val_err: EMPTY_METADATA_ERR_MSG,
        },
      ];
    },
    add_metadata_kv: function () {
      this.user_defined_metadata.push(this.get_default_user_defined_metadata()[0]);
    },
    remove_metadata_kv: function (idx) {
      if (this.user_defined_metadata.length > 0) {
        this.user_defined_metadata.splice(idx, 1);
        // If a row was removed, need to check for dups again
        this.check_duplicate_metadata_keys();
      }
    },
    update_metadata: function (i, type, new_entry) {
      const row_info = this.user_defined_metadata[i];
      row_info[type] = new_entry;

      const err_key = `${type}_err`;
      row_info[err_key] = "";
      if (new_entry === "") {
        row_info[err_key] = EMPTY_METADATA_ERR_MSG;
      }
      if (type === "key") {
        this.check_duplicate_metadata_keys();
      }
    },
    check_duplicate_metadata_keys: function () {
      const all_keys = this.user_defined_metadata.map((meta_info) => meta_info.key);
      all_keys.map((key, idx) => {
        if (key === "") return; // don't mark empty cells as dups, they have their own error message

        const first_idx_of_key = all_keys.indexOf(key);
        if (idx !== first_idx_of_key) {
          this.user_defined_metadata[idx].key_err = DUPLICATE_METADATA_KEY_ERR_MSG;
          this.user_defined_metadata[first_idx_of_key].key_err = DUPLICATE_METADATA_KEY_ERR_MSG;
        } else {
          this.user_defined_metadata[idx].key_err = "";
        }
      });
    },
    get_formatted_user_defined_metadata: function () {
      const formatted_meta = {};
      this.user_defined_metadata.map((meta_info) => {
        formatted_meta[meta_info.key] = meta_info.val;
      });
      return formatted_meta;
    },
    handle_snapshot_toggle: function (state) {
      this.run_recording_snapshot_current = state;
    },
  },
};
</script>
<style scoped>
.div__recording-name-input-background {
  pointer-events: all;
  transform: rotate(0deg);
  position: absolute;
  height: 500px;
  width: 700px;
  top: 0;
  left: 0;
  visibility: visible;
  color: #1c1c1c;
  border-color: #000000;
  background: rgb(17, 17, 17);
  z-index: 3;
}

.div__outer_container {
  display: flex;
  flex-direction: column;
  position: relative;
  width: 100%;
  height: 100%;
}

.span__recording-name-input-label {
  pointer-events: all;
  line-height: 100%;
  transform: rotate(0deg);
  overflow: hidden;
  position: relative;
  height: 10%;
  padding-top: 3%;
  visibility: visible;
  user-select: none;
  font-family: Muli;
  font-weight: normal;
  font-style: normal;
  text-decoration: none;
  font-size: 17px;
  color: rgb(255, 255, 255);
  text-align: center;
  width: 100%;
}
.div__recording-name-input-box {
  position: relative;
  z-index: 24;
  margin-left: 22%;
  height: 22%;
}

.div__metadata_container {
  height: 43%;
}

.div__metadata-backdrop {
  transform: rotate(0deg);
  box-sizing: border-box;
  position: relative;
  height: 80%;
  max-height: 80%;
  margin-top: 1%;
  visibility: visible;
  border: 0px none #1111;
  pointer-events: all;
  align-items: center;
  overflow-y: scroll;
  background: #191919;
  /* width: 870px; */
}

::-webkit-scrollbar {
  -webkit-appearance: none;
  height: 8px;
  overflow: visible;
}

::-webkit-scrollbar-thumb {
  background-color: #2f2f2f;
  overflow: visible;
}

::-webkit-scrollbar-track {
  background-color: #727171;
  overflow: visible;
}

.div__metadata_title {
  display: flex;
  flex-direction: row;
  justify-content: space-evenly;
}

.span__metadata_label {
  color: rgb(183, 183, 183);
}

.div__metadata-add-remove-container {
  display: flex;
  flex-direction: row;
  justify-content: space-evenly;
  width: 10%;
}

.span__axis-controls-add-remove-kv-button {
  font-weight: normal;
  position: relative;
  color: rgb(183, 183, 183);
  height: 24px;
  width: 24px;
}

.span__axis-controls-add-remove-kv-button:hover {
  color: #ffffff;
  transition: color 0.15s;
}

.div__metadata-row {
  display: flex;
  flex-direction: row;
  justify-content: space-evenly;
  width: 90%;
  height: 70px;
}

.span__metadata_row_label {
  width: 10%;
  text-align: right;
  padding-top: 13px;
  color: rgb(183, 183, 183);
  position: relative;
}

.div__metadata_input_container {
  width: 35%;
  justify-content: center;
  position: relative;
}

.div__toggle-container {
  font-family: Muli;
  font-size: 16px;
  color: rgb(183, 183, 183);
  text-align: center;
  display: flex;
  flex-direction: row;
  justify-content: space-evenly;
  position: relative;
  height: 15%;
  padding-top: 2.5%;
}

.div__confirm-button-container {
  height: 10%;
  position: relative;
}
</style>
