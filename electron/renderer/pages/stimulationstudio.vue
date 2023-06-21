<template>
  <div class="div__stimulation-studio-container">
    <StimulationStudio />
  </div>
</template>

<script>
import { StimulationStudio } from "@curi-bio/mantarray-frontend-components";
export default {
  components: {
    StimulationStudio,
  },
  layout: "default",
};
</script>

<style type="text/css">
.div__stimulation-studio-container {
  top: 45px;
  position: absolute;
}
</style>
