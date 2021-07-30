import {
  mount,
  shallowMount,
  createLocalVue,
  RouterLinkStub,
} from "@vue/test-utils";
import WaveformScreenView from "@/renderer/pages/index.vue";
import SideBar from "@/renderer/layouts/default.vue";
import {
  Waveform,
  FLASK_STATUS_ENUMS,
  system_status_regexp,
} from "@curi-bio/mantarray-frontend-components";

// from https://dev.to/bawa_geek/how-to-setup-jest-testing-in-nuxt-js-project-5c84
import { config } from "@vue/test-utils";
config.stubs.nuxt = { template: "<div />" };

import Vuex from "vuex";

const MockAxiosAdapter = require("axios-mock-adapter");
const wait_for_expect = require("wait-for-expect");
import axios from "axios";

let waveform_wrapper = null;
let sidebar_wrapper = null;

const localVue = createLocalVue();
localVue.component("NuxtLink", {});
localVue.use(Vuex);
let NuxtStore;
let store;
let mocked_axios;
const propsData = {};

describe("WaveformScreenView", () => {
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
    mocked_axios.restore();
  });

  describe("Given /system_status is mocked to respond with 200 and state LIVE_VIEW_ACTIVE", () => {
    beforeEach(() => {
      mocked_axios.onGet(system_status_regexp).reply(200, {
        ui_status_code: FLASK_STATUS_ENUMS.MESSAGE.LIVE_VIEW_ACTIVE_uuid,
        in_simulation_mode: true,
      });
    });
    test("When SideBar is mounted, Then status pinging gets started", async () => {
      // confirm precondition
      expect(store.state.flask.status_ping_interval_id).toBeNull();

      sidebar_wrapper = shallowMount(SideBar, {
        propsData,
        store,
        localVue,
        stubs: { NuxtLink: RouterLinkStub },
      });
      await wait_for_expect(() => {
        expect(store.state.flask.status_ping_interval_id).not.toBeNull();
      });
      sidebar_wrapper.destroy();
    });

    describe("Given default layout is mounted", () => {
      beforeEach(() => {
        sidebar_wrapper = shallowMount(SideBar, {
          propsData,
          store,
          localVue,
          stubs: { NuxtLink: RouterLinkStub },
        });
      });
      afterEach(async () => {
        sidebar_wrapper.destroy();
      });
      test("When WaveformScreenView is mounted, Then Waveform components should exist", async () => {
        waveform_wrapper = mount(WaveformScreenView, {
          propsData,
          store,
          localVue,
        });
        expect(waveform_wrapper.findComponent(Waveform).exists()).toBe(true);
        waveform_wrapper.destroy();
      });
    });
  });
});
