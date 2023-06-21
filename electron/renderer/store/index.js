// adapted from https://stackoverflow.com/questions/53446792/nuxt-vuex-how-do-i-break-down-a-vuex-module-into-separate-files

import Vuex from "vuex";
import { settingsStoreModule, systemStoreModule, stimulationStoreModule } from "@curi-bio/ui";

const createStore = () => {
  return new Vuex.Store({
    // namespaced: true, // this doesn't seem to do anything...(Eli 4/1/20) each module seems to need to be namespaced: true individually https://vuex.vuejs.org/guide/modules.html
    modules: {
      system: systemStoreModule,
      settings: settingsStoreModule,
      stimulation: stimulationStoreModule,
    },
  });
};

export default createStore;
