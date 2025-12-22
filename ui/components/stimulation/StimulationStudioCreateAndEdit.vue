<template>
  <div class="div__simulationstudio-backdrop">
    <span class="span__stimulationstudio-layout-create_edit-header-label"
      >Create/Edit Stimulation Protocol</span
    >
    <span class="span__stimulationstudio-layout-subheader-label">Select/Create Protocol</span>
    <div class="div__stimulationstudio-select-dropdown-container">
      <SelectDropDown
        :options_text="protocol_list"
        :show_delete_option="show_delete_option"
        :input_width="input_width"
        :input_height="input_height"
        @selection-changed="selected_protocol_change"
        @handle-delete="handle_delete"
      >
        <template v-for="item in protocol_list" #[item.letter]>
          <span :key="item.letter" class="span__stim-type-logo">
            <StimTypeLogo :stimulation_type="stim_type(item)" style="overflow: visible; margin-top: 4px" />
          </span>
        </template>
      </SelectDropDown>
    </div>
    <canvas class="canvas__stimulationstudio-button-separator" />
    <div
      v-for="(value, key, idx) in btn_labels"
      :id="key"
      :key="key"
      :class="get_class(idx)"
      :style="value"
      @click.exact="handle_click(idx)"
    >
      <span :class="get_label_class(idx)">{{ key }}</span>
    </div>
    <div
      v-for="(value, key, idx) in import_export_btn_labels"
      id="import_export_button"
      :key="key"
      @click.exact="handle_import_export(idx)"
    >
      <div :class="'div__stimulationstudio-btn-container'" :style="value">
        <span type="button" :class="'span__stimulationstudio-btn-label'">{{ key }}</span>
      </div>
    </div>
  </div>
</template>

<script>
import StimTypeLogo from "@/components/stimulation/StimTypeLogo.vue";
import SelectDropDown from "@/components/basic_widgets/SelectDropDown.vue";
import { mapActions, mapState, mapMutations, mapGetters } from "vuex";

/**
 * @vue-data {Object} btn_labels - Label and style of buttons
 * @vue-data {Object} import_export_btn_labels - Label and style of export and import buttons
 * @vue-data {Int} selected_protocol_idx - Index of selected protocol from dropdown
 * @vue-data {Int} input_height - Height passed down to dropdown for styling
 * @vue-data {Int} input_width -  Width passed down to dropdown for styling
 * @vue-data {Array} protocol_list - Availble protocols to display in dropdown
 * @vue-event {Event} update_protocols - Gets called when a change to the available protocol list occurs to update next available color/letter assignment and dropdown options
 * @vue-event {Event} selected_protocol_change - Changes when a new protocol is selected from dropdown
 * @vue-event {Event} handle_click - Performs functions based on which button is clicked regarding assigning and clearing protocols from plate editor
 * @vue-event {Event} get_class - Dynamically renders button class depending on if button is disabled
 * @vue-event {Event} get_label_class - Dynamically renders button labels class depending on if button is disabled
 * @vue-event {Event} handle_import_export - On click, it reassigns function to input[type=file] to upload file
 * @vue-event {Event} handle_import - Dispatches imported file to be handled in store
 * @vue-event {Event} handle_export - Dispatches request to store to write current protocol
 */

export default {
  name: "StimulationStudioCreateAndEdit",
  components: {
    SelectDropDown,
    StimTypeLogo,
  },
  props: {
    disable_edits: { type: Boolean, default: false }, // TODO actually pass this prop in
  },
  data() {
    return {
      btn_labels: {
        "Apply to Selection": " left: 19%; top: 49%; ",
        "Clear Selection": " left: 51%; top: 49%; ",
      },
      import_export_btn_labels: {
        "Import Protocol(s)": " left: 19%; top: 76%; width: 30%;",
        "Export Protocol(s)": " left: 51%; top: 76%; width: 30%;",
      },
      selected_protocol_idx: 0,
      input_height: 45,
      input_width: 600,
    };
  },
  computed: {
    ...mapState("stimulation", ["protocol_list", "edit_mode"]),
    ...mapGetters("stimulation", ["get_platemap_stim_type", "get_stim_type"]),
    edit_mode_status: function () {
      return this.edit_mode.status;
    },
  },
  watch: {
    protocol_list: function () {
      this.selected_protocol_idx = 0;
    },
    edit_mode_status: function () {
      if (!this.edit_mode_status) {
        this.selected_protocol_idx = 0;
      } else {
        const { letter } = this.edit_mode;
        this.selected_protocol_idx = this.protocol_list.findIndex((protocol) => protocol.letter === letter);
      }
    },
  },
  methods: {
    ...mapActions("stimulation", [
      "edit_selected_protocol",
      "handle_import_protocol",
      "handle_export_protocol",
    ]),
    ...mapMutations("stimulation", [
      "set_edit_mode_off",
      "reset_protocol_editor",
      "clear_selected_protocol",
      "apply_selected_protocol",
      "set_selected_protocol_for_edit",
    ]),
    async selected_protocol_change(idx) {
      this.selected_protocol_idx = idx;
      const selected_protocol = this.protocol_list[idx];

      if (idx === 0) {
        this.set_edit_mode_off();
        this.reset_protocol_editor();
      } else {
        await this.edit_selected_protocol(selected_protocol);
      }

      this.$emit("handle_selection_change", selected_protocol);
    },
    stim_type(item) {
      return (item.protocol || {}).stimulation_type || "C";
    },
    handle_delete(item) {
      this.$bvModal.show("del-protocol-modal");
    },
    disable_selection_btn(idx) {
      if (this.disable_edits) {
        return true;
      } else if (idx === 0) {
        return (
          this.selected_protocol_idx === 0 ||
          (this.get_platemap_stim_type !== null && this.get_platemap_stim_type !== this.get_stim_type)
        );
      }
      return false;
    },
    handle_click(idx) {
      if (this.disable_selection_btn(idx)) {
        return;
      }

      if (idx === 0) {
        const selected_protocol = this.protocol_list[this.selected_protocol_idx];
        this.apply_selected_protocol(selected_protocol);
      } else if (idx === 1) {
        this.clear_selected_protocol();
      }
    },
    get_class(idx) {
      return this.disable_selection_btn(idx)
        ? "div__stimulationstudio-btn-container-disable"
        : "div__stimulationstudio-btn-container";
    },
    get_label_class(idx) {
      return this.disable_selection_btn(idx)
        ? "span__stimulationstudio-btn-label-disable"
        : "span__stimulationstudio-btn-label";
    },
    handle_import_export(idx) {
      if (idx === 0) {
        // this adds and removes the input element to be able to allow importing the same file twice in a row.
        // Otherwise the @change event won't get triggered if the same file is selected twice.
        const input_el = document.createElement("input");
        document.body.appendChild(input_el);
        input_el.setAttribute("ref", "file");
        input_el.setAttribute("type", "file");
        input_el.addEventListener("change", (e) => this.handle_import(e.target.files));
        input_el.click();
        input_el.remove();
      } else if (idx === 1) {
        this.handle_export();
      }
    },
    handle_import(file) {
      this.handle_import_protocol(file[0]);
    },
    handle_export() {
      this.handle_export_protocol();
    },
    show_delete_option(p) {
      return p.letter.trim().length !== 0;
    },
  },
};
</script>

<style scoped>
.div__simulationstudio-backdrop {
  display: flex;
  justify-content: center;
  box-sizing: border-box;
  background: rgb(17, 17, 17);
  position: absolute;
  width: 640px;
  height: 280px;
  visibility: visible;
  border-radius: 10px;
  box-shadow: rgba(0, 0, 0, 0.7) 0px 0px 10px 0px;
  pointer-events: all;
  z-index: 2;
}

.span__stimulationstudio-layout-create_edit-header-label {
  pointer-events: all;
  line-height: 100%;
  transform: rotate(0deg);
  overflow: hidden;
  position: absolute;
  padding-top: 15px;
  visibility: visible;
  user-select: none;
  font-family: Muli;
  font-size: 19px;
  color: rgb(255, 255, 255);
  text-align: center;
}

.span__stimulationstudio-layout-subheader-label {
  pointer-events: all;
  line-height: 100%;
  transform: rotate(0deg);
  overflow: hidden;
  position: absolute;
  top: 45px;
  visibility: visible;
  user-select: none;
  font-family: Muli;
  font-weight: normal;
  font-style: normal;
  text-decoration: none;
  font-size: 17px;
  color: rgb(183, 183, 183);
}

.div__stimulationstudio-select-dropdown-container {
  pointer-events: all;
  line-height: 100%;
  transform: rotate(0deg);
  position: absolute;
  width: 210px;
  height: 50px;
  top: 75px;
  right: 410px;
  padding: 5px;
  z-index: 3;
}

.span__stim-type-logo {
  height: 21px;
  width: 19px;
  fill: white;
  margin-right: 5px;
  font-size: 3px;
}

.div__stimulationstudio-select-dropdown-container > .div__input-dropdown-background {
  background: none;
  border: none;
}

.div__stimulationstudio-btn-container {
  display: flex;
  justify-content: center;
  align-content: center;
  position: absolute;
  width: 30%;
  height: 45px;
  background: #b7b7b7;
}

.div__stimulationstudio-btn-container-disable {
  display: flex;
  justify-content: center;
  align-content: center;
  position: absolute;
  width: 30%;
  height: 45px;
  background: #b7b7b7c9;
}

.div__stimulationstudio-btn-container:hover {
  background: #b7b7b7c9;
  cursor: pointer;
}

.span__stimulationstudio-btn-label {
  transform: translateZ(0px);
  line-height: 45px;
  font-family: Muli;
  font-size: 16px;
  color: rgb(0, 0, 0);
}

.span__stimulationstudio-btn-label-disable {
  transform: translateZ(0px);
  line-height: 45px;
  font-family: Muli;
  font-size: 16px;
  color: #6e6f72;
}

.canvas__stimulationstudio-button-separator {
  transform: rotate(0deg);
  pointer-events: all;
  position: absolute;
  width: 620px;
  height: 2px;
  top: 70%;
  visibility: visible;
  background-color: #3f3f3f;
  opacity: 0.5;
}
</style>
