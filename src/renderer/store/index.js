// adapted from https://stackoverflow.com/questions/53446792/nuxt-vuex-how-do-i-break-down-a-vuex-module-into-separate-files

import Vuex from "vuex";
import {
  playback_store_module,
  waveform_store_module,
  twentyfourcontrols_store_module,
  flask_store_module,
  settings_store_module,
} from "@curi-bio/mantarray-frontend-components";

const createStore = () => {
  return new Vuex.Store({
    // namespaced: true, // this doesn't seem to do anything...(Eli 4/1/20) each module seems to need to be namespaced: true individually https://vuex.vuejs.org/guide/modules.html
    modules: {
      playback: playback_store_module,
      waveform: waveform_store_module,
      twentyfourcontrols: twentyfourcontrols_store_module,
      flask: flask_store_module,
      settings: settings_store_module,
    },
  });
};

export default createStore;
