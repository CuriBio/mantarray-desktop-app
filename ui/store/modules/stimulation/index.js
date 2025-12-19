import mutations from "./mutations";
import { default as getters, get_default_protocol_editor_state } from "./getters";
import actions from "./actions";
import { STIM_STATUS, STIM_LID_TYPE_TO_STIM_TYPE } from "./enums";

const state = () => ({
  selected_wells: [],
  protocol_list: [{ letter: "", color: "", label: "Create New" }],
  protocol_assignments: {},
  protocol_editor: get_default_protocol_editor_state(),
  current_assignment: { letter: "", color: "" },
  x_axis_values: [],
  y_axis_values: [],
  repeat_colors: [],
  y_axis_scale: 120,
  delay_blocks: [],
  stim_play_state: false,
  protocol_completion_timepoints: Array(24).fill(-1), // Tanner (12/15/23): this is only intended to be used for the stim banner at the moment
  x_axis_unit_name: "milliseconds",
  x_axis_time_idx: 0,
  edit_mode: { status: false, label: "", color: "" },
  stim_status: STIM_STATUS.CALIBRATION_NEEDED,
  hovered_pulse: {
    idx: null,
    indices: [],
    color: null,
  },

  invalid_imported_protocols: [],
  stim_start_time_idx: null,
});

export default {
  namespaced: true,
  state,
  mutations,
  getters,
  actions,
  STIM_STATUS,
  STIM_LID_TYPE_TO_STIM_TYPE,
};
