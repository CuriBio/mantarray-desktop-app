<template>
  <div>
    <div class="div__y-axis-controls-container">
      <YAxisControls :height="'885px'" />
    </div>
    <div class="div__grid-of-waveforms">
      <div
        v-for="waveform_index in Array(6).keys()"
        :key="waveform_index"
        :style="
          'position: absolute; top: ' +
          (waveform_index % 2) * 422 +
          'px; left: ' +
          Math.floor(waveform_index / 2) * 524 +
          'px;'
        "
      >
        <ContinuousWaveform
          :display_waveform_idx="waveform_index"
          :x_label="'Time (seconds)'"
          :y_label="'Absolute Force (µN)'"
          :display_data_prior_to_current_timepoint="true"
        />
      </div>
    </div>
    <div v-show="simulation_mode" class="div__simulation_mode_overlay">
      <div class="div__simulation_mode_text">
        Simulation <br />
        Mode
      </div>
    </div>
    <div class="div__x-axis-controls-container">
      <XAxisControls />
    </div>
  </div>
</template>

<script>
import { ContinuousWaveform, XAxisControls, YAxisControls } from "@curi-bio/mantarray-frontend-components";
import { mapState } from "vuex";
export default {
  components: {
    ContinuousWaveform,
    XAxisControls,
    YAxisControls,
  },
  layout: "default",
  computed: {
    ...mapState("flask", ["simulation_mode"]),
  },
};
</script>

<style type="text/css">
.div__y-axis-controls-container {
  top: 45px;
  position: absolute;
}
.div__x-axis-controls-container {
  position: absolute;
  left: 45px;
  top: 885px;
  width: 1584px;
}
.div__grid-of-waveforms,
.div__simulation_mode_overlay {
  position: absolute;
  top: 45px;
  left: 45px;
  height: 840px;
  width: 1584px;
  background-color: black;
}
.div__simulation_mode_text {
  font-family: Muli;
  font-size: 250px;
  color: #ffffff;
  position: relative;
  z-index: 1;
  font-style: italic;
  margin-left: 85px;
  text-align: center;
  font-weight: 600;
  opacity: 0.8;
}
.div__simulation_mode_overlay {
  opacity: 0.3;
  display: flex;
  justify-content: center;
  align-items: center;
  background-color: #4c4c4c;
}
</style>
