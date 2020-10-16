import { mount, shallowMount, createLocalVue } from "@vue/test-utils";
import StartPage from "@/renderer/pages/index.vue";
import {
  Waveform,
  FLASK_STATUS_ENUMS,
  system_status_regexp,
} from "@curi-bio/mantarray-frontend-components";

import Vuex from "vuex";

const MockAxiosAdapter = require("axios-mock-adapter");
const wait_for_expect = require("wait-for-expect");
import axios from "axios";

let wrapper = null;

const localVue = createLocalVue();
localVue.use(Vuex);
let NuxtStore;
let store;
let mocked_axios;
const propsData = {};
beforeAll(async () => {
  // note the store will mutate across tests, so make sure to re-create it in beforeEach
  const storePath = `${process.env.buildDir}/store.js`;
  NuxtStore = await import(storePath);
});

beforeEach(async () => {
  store = await NuxtStore.createStore();
  mocked_axios = new MockAxiosAdapter(axios);
});
afterEach(async () => {
  // clean up any pinging that was started
  store.commit("flask/stop_status_pinging");
  wrapper.destroy();
  mocked_axios.restore();
});

describe("Start Page", () => {
  describe("Given /system_status is mocked to respond with 200 and state CALIBRATION_NEEDED", () => {
    beforeEach(() => {
      mocked_axios.onGet(system_status_regexp).reply(200, {
        ui_status_code: FLASK_STATUS_ENUMS.MESSAGE.LIVE_VIEW_ACTIVE_uuid,
        in_simulation_mode: true,
      });
    });
    test("When mounted, Waveform components should exist", async () => {
      wrapper = mount(StartPage, { propsData, store, localVue });
      expect(wrapper.findComponent(Waveform).exists()).toBe(true);
    });

    test("When mounted, Then status pinging gets started", async () => {
      // confirm pre-condition
      expect(store.state.flask.status_ping_interval_id).toBe(null);
      wrapper = shallowMount(StartPage, { propsData, store, localVue });
      await wait_for_expect(() => {
        expect(store.state.flask.status_ping_interval_id).not.toBe(null);
      });
    });
  });
});
