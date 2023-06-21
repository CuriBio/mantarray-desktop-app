<template>
  <div class="div__platemap-editor-container">
    <PlateMapEditor />
  </div>
</template>

<script>
import { PlateMapEditor } from "@curi-bio/mantarray-frontend-components";
export default {
  components: {
    PlateMapEditor,
  },
  layout: "default",
};
</script>

<style type="text/css">
.div__platemap-editor-container {
  top: 45px;
  position: absolute;
}
</style>
