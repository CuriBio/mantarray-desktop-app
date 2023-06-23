<template>
  <div class="div__heatmap-container">
    <HeatMap />
  </div>
</template>

<script>
import { HeatMap } from "@curi-bio/ui";
export default {
  components: {
    HeatMap,
  },
  layout: "default",
};
</script>

<style type="text/css">
.div__heatmap-container {
  top: 45px;
  position: absolute;
}
</style>
