/**
 * @jest-environment node
 */
const MockAdapter = require("axios-mock-adapter");

import http_client from "../main/http_client.js";

const TEST_URL = "https://pulse3d.curibio-test.com/versions";
const TEST_VERSION_INFO = [{ version: "1.0.0", state: "external" }];
// overriding the delay per request so the tests don't wait between retries
const NO_DELAY = { "axios-retry": { retryDelay: () => 0 } };

const reject_with_code = (code, message, delay_ms = 0) => async (config) => {
  await new Promise((resolve) => setTimeout(resolve, delay_ms));
  throw Object.assign(new Error(message), { code, config });
};

describe("http_client.js", () => {
  let mocked_cloud;
  let spied_console_log;
  beforeEach(() => {
    mocked_cloud = new MockAdapter(http_client.cloud_client);
    spied_console_log = jest.spyOn(console, "log").mockImplementation(() => {});
  });
  afterEach(() => {
    mocked_cloud.restore();
    jest.restoreAllMocks();
  });

  describe("cloud_client", () => {
    test("When a GET times out, Then it is retried with the full timeout and the response from the retry is returned", async () => {
      // the first attempt takes a moment so the retry would get less than the full timeout if it were shared
      mocked_cloud
        .onGet(TEST_URL)
        .replyOnce(reject_with_code("ECONNABORTED", "timeout of 10000ms exceeded", 50))
        .onGet(TEST_URL)
        .replyOnce(200, TEST_VERSION_INFO);

      const actual = await http_client.cloud_client.get(TEST_URL, NO_DELAY);

      expect(actual.data).toStrictEqual(TEST_VERSION_INFO);
      expect(mocked_cloud.history.get).toHaveLength(2);
      expect(mocked_cloud.history.get[1].timeout).toBe(10000);
      expect(spied_console_log).toHaveBeenCalledWith(
        `Retry 1 of 4 for ${TEST_URL} after: timeout of 10000ms exceeded`
      );
    });
    test("When a GET fails because the host name could not be resolved, Then it is retried", async () => {
      mocked_cloud
        .onGet(TEST_URL)
        .replyOnce(reject_with_code("ENOTFOUND", "getaddrinfo ENOTFOUND pulse3d.curibio-test.com"))
        .onGet(TEST_URL)
        .replyOnce(200, TEST_VERSION_INFO);

      const actual = await http_client.cloud_client.get(TEST_URL, NO_DELAY);

      expect(actual.data).toStrictEqual(TEST_VERSION_INFO);
      expect(mocked_cloud.history.get).toHaveLength(2);
    });
    test.each([500, 503, 429])("When a GET fails with status %d, Then it is retried", async (status) => {
      mocked_cloud.onGet(TEST_URL).replyOnce(status).onGet(TEST_URL).replyOnce(200, TEST_VERSION_INFO);

      const actual = await http_client.cloud_client.get(TEST_URL, NO_DELAY);

      expect(actual.data).toStrictEqual(TEST_VERSION_INFO);
      expect(mocked_cloud.history.get).toHaveLength(2);
    });
    test.each([400, 401, 404])("When a GET fails with status %d, Then it is not retried", async (status) => {
      mocked_cloud.onGet(TEST_URL).reply(status);

      await expect(http_client.cloud_client.get(TEST_URL, NO_DELAY)).rejects.toMatchObject({
        response: { status },
      });
      expect(mocked_cloud.history.get).toHaveLength(1);
    });
    test("When a POST times out, Then it is not retried", async () => {
      mocked_cloud.onPost(TEST_URL).timeout();

      await expect(http_client.cloud_client.post(TEST_URL, {}, NO_DELAY)).rejects.toMatchObject({
        code: "ECONNABORTED",
      });
      expect(mocked_cloud.history.post).toHaveLength(1);
    });
    test("When every attempt fails, Then the error from the last attempt is thrown after the first attempt and 4 retries", async () => {
      mocked_cloud.onGet(TEST_URL).networkError();

      await expect(http_client.cloud_client.get(TEST_URL, NO_DELAY)).rejects.toThrow("Network Error");
      expect(mocked_cloud.history.get).toHaveLength(5);
    });
  });
});
