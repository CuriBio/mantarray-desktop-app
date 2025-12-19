<template>
  <div style="overflow: hidden">
    <LightningLogo v-if="stimulation_type === 'C'" />
    <SunLogo v-if="stimulation_type === 'O'" style="margin-top: -0.7em" />
  </div>
</template>
<script>
import LightningLogo from "@/components/svgs/LightningLogo.vue";
import SunLogo from "@/components/svgs/SunLogo.vue";
export default {
  name: "StimTypeLogo",
  components: {
    LightningLogo,
    SunLogo,
  },
  props: {
    stimulation_type: { type: String, default: "C" },
  },
};
</script>
