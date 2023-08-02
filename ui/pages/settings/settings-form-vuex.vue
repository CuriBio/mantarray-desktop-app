<template>
  <div>
    <SettingsForm></SettingsForm>
  </div>
</template>

<script>
// import { SettingsForm } from "@/dist/mantarray.common";
import SettingsForm from "@/components/settings/SettingsForm.vue";

export default {
  components: {
    SettingsForm,
  },
  created: function () {
    this.$store.commit("settings/set_beta_2_mode", true);
    this.$store.commit("settings/set_pulse3d_versions", ["12.34.56", "0.24.6", "1.0.0"]);
  },
};
</script>
s
