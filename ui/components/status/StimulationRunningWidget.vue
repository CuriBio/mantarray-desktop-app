<template>
  <div>
    <div v-if="is_visible" :class="{ flash: is_flashing }">Stimulation is Running</div>
  </div>
</template>

<script>
import { mapState, mapGetters } from "vuex";
import { STATUS } from "@/store/modules/flask/enums";

export default {
  name: "StimulationRunningWidget",
  data() {
    return { show_stim_banner: false };
  },

  computed: {
    ...mapGetters({
      status_uuid: "flask/status_id",
    }),
    ...mapState("stimulation", ["stim_play_state", "protocol_completion_timepoints"]),
    ...mapState("playback", ["x_time_index"]),
    is_flashing() {
      return this.show_stim_banner;
    },
    is_visible() {
      return this.show_stim_banner;
    },
    has_all_stim_completed() {
      return this.protocol_completion_timepoints.every((t) => t !== null && this.x_time_index >= t);
    },
    is_data_streaming() {
      return [STATUS.MESSAGE.BUFFERING, STATUS.MESSAGE.LIVE_VIEW_ACTIVE, STATUS.MESSAGE.RECORDING].includes(
        this.status_uuid
      );
    },
  },
  watch: {
    has_all_stim_completed() {
      if (this.has_all_stim_completed) {
        this.show_stim_banner = false;
      }
    },
    stim_play_state(state) {
      if (state) {
        this.show_stim_banner = true;
      } else if (!this.is_data_streaming) {
        this.show_stim_banner = false;
      }
    },
  },
};
</script>

<style>
.flash {
  animation: flash 1s infinite;
  color: white;
  background-color: red;
  padding: 3px;
}

@keyframes flash {
  0% {
    opacity: 1;
  }
  50% {
    opacity: 0;
  }
  100% {
    opacity: 1;
  }
}
</style>
