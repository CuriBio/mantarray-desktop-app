/**
 * @jest-environment node
 */
// the node environment makes axios use its node adapter, the same one it uses in the electron main process
const axios = require("axios");
const dns = require("dns");
const https = require("https");
const net = require("net");

import http_client from "../main/http_client.js";

const TEST_URL = "https://pulse3d.curibio-test.com/versions";
const TEST_RESPONSE = { data: [{ version: "1.0.0", state: "external" }] };

const create_network_error = (code, message) => Object.assign(new Error(message), { code });
const create_http_error = (status) => Object.assign(new Error(`status ${status}`), { response: { status } });

describe("http_client.js", () => {
  let spied_console_log;
  beforeEach(() => {
    spied_console_log = jest.spyOn(console, "log").mockImplementation(() => {});
  });
  afterEach(() => {
    jest.restoreAllMocks();
  });

  describe("request_with_retry", () => {
    test("When the first attempt succeeds, Then the response is returned after a single request with a default timeout", async () => {
      const spied_request = jest.spyOn(axios, "request").mockResolvedValue(TEST_RESPONSE);

      const actual = await http_client.request_with_retry({ url: TEST_URL });

      expect(actual).toBe(TEST_RESPONSE);
      expect(spied_request).toHaveBeenCalledTimes(1);
      expect(spied_request).toHaveBeenCalledWith({
        url: TEST_URL,
        timeout: 10000,
        httpsAgent: expect.any(https.Agent),
      });
    });
    test("When the caller sets other request options, Then they are passed to axios and can override the default timeout", async () => {
      const spied_request = jest.spyOn(axios, "request").mockResolvedValue(TEST_RESPONSE);
      const request_config = { url: TEST_URL, method: "put", data: { a: 1 }, timeout: 500 };

      await http_client.request_with_retry(request_config);

      expect(spied_request).toHaveBeenCalledWith({ ...request_config, httpsAgent: expect.any(https.Agent) });
    });
    test("When the first attempts fail, Then the request is retried and the response from the first successful attempt is returned", async () => {
      const spied_request = jest
        .spyOn(axios, "request")
        .mockRejectedValueOnce(create_network_error("ETIMEDOUT", "connect ETIMEDOUT 3.20.213.128:443"))
        .mockRejectedValueOnce(create_http_error(503))
        .mockResolvedValueOnce(TEST_RESPONSE);

      const actual = await http_client.request_with_retry({ url: TEST_URL }, { initial_delay_ms: 0 });

      expect(actual).toBe(TEST_RESPONSE);
      expect(spied_request).toHaveBeenCalledTimes(3);
      expect(spied_console_log).toHaveBeenCalledWith(`GET ${TEST_URL} succeeded on attempt 3 of 4`);
    });
    test("When every attempt fails, Then the error from the last attempt is thrown after one attempt plus the retries", async () => {
      const last_error = create_network_error("ECONNABORTED", "timeout of 10000ms exceeded");
      const spied_request = jest
        .spyOn(axios, "request")
        .mockRejectedValueOnce(create_network_error("ETIMEDOUT", "connect ETIMEDOUT"))
        .mockRejectedValueOnce(create_network_error("ETIMEDOUT", "connect ETIMEDOUT"))
        .mockRejectedValueOnce(last_error);

      await expect(
        http_client.request_with_retry({ url: TEST_URL }, { retries: 2, initial_delay_ms: 0 })
      ).rejects.toBe(last_error);
      expect(spied_request).toHaveBeenCalledTimes(3);
    });
    test("When attempts fail, Then the delay before each retry doubles", async () => {
      jest.spyOn(axios, "request").mockRejectedValue(create_network_error("ETIMEDOUT", "connect ETIMEDOUT"));
      const spied_set_timeout = jest.spyOn(global, "setTimeout");

      await expect(
        http_client.request_with_retry({ url: TEST_URL }, { retries: 3, initial_delay_ms: 5 })
      ).rejects.toThrow();

      const delays = spied_set_timeout.mock.calls.map(([, delay]) => delay);
      expect(delays).toEqual([5, 10, 20]);
    });
    test.each([400, 401, 404])(
      "When the server rejects the request with status %d, Then it is not retried",
      async (status) => {
        const spied_request = jest.spyOn(axios, "request").mockRejectedValue(create_http_error(status));

        await expect(
          http_client.request_with_retry({ url: TEST_URL }, { initial_delay_ms: 0 })
        ).rejects.toThrow();
        expect(spied_request).toHaveBeenCalledTimes(1);
      }
    );
    test("When the server is rate limiting, Then the request is retried", async () => {
      const spied_request = jest
        .spyOn(axios, "request")
        .mockRejectedValueOnce(create_http_error(429))
        .mockResolvedValueOnce(TEST_RESPONSE);

      await http_client.request_with_retry({ url: TEST_URL }, { initial_delay_ms: 0 });

      expect(spied_request).toHaveBeenCalledTimes(2);
    });
    test("When an attempt fails, Then the method, URL without its query string, error, and resolved IP are logged with the attempt number", async () => {
      jest.spyOn(http_client, "create_ip_recording_agent").mockReturnValue({ resolved_ip: "3.20.213.128" });
      jest
        .spyOn(axios, "request")
        .mockRejectedValue(create_network_error("ETIMEDOUT", "connect ETIMEDOUT 3.20.213.128:443"));

      await expect(
        http_client.request_with_retry(
          { url: `${TEST_URL}?signature=secret`, method: "post" },
          { retries: 1, initial_delay_ms: 0 }
        )
      ).rejects.toThrow();

      expect(spied_console_log.mock.calls).toEqual([
        [
          `POST ${TEST_URL} failed on attempt 1 of 2: ETIMEDOUT connect ETIMEDOUT 3.20.213.128:443 (resolved IP: 3.20.213.128)`,
        ],
        [
          `POST ${TEST_URL} failed on attempt 2 of 2: ETIMEDOUT connect ETIMEDOUT 3.20.213.128:443 (resolved IP: 3.20.213.128)`,
        ],
      ]);
    });
    test("When a real request fails to connect, Then the logged resolved IP is the address that axios tried", async () => {
      // get a port that nothing is listening on
      const server = net.createServer();
      await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
      const closed_port = server.address().port;
      await new Promise((resolve) => server.close(resolve));
      jest.spyOn(dns, "lookup").mockImplementation((hostname, options, callback) => {
        callback(null, "127.0.0.1", 4);
      });
      const url = `https://localhost:${closed_port}/versions`;

      await expect(
        http_client.request_with_retry({ url, timeout: 2000 }, { retries: 0 })
      ).rejects.toMatchObject({ code: "ECONNREFUSED" });

      expect(spied_console_log).toHaveBeenCalledWith(
        `GET ${url} failed on attempt 1 of 1: ECONNREFUSED connect ECONNREFUSED 127.0.0.1:${closed_port} (resolved IP: 127.0.0.1)`
      );
    });
  });

  describe("describe_request_error", () => {
    test("When the server responded with an error status, Then the status is described", () => {
      const error = { response: { status: 500, statusText: "Internal Server Error" } };

      expect(http_client.describe_request_error(error, "3.20.213.128")).toBe(
        "HTTP 500 Internal Server Error (resolved IP: 3.20.213.128)"
      );
    });
    test("When the error has no code and the IP is not known, Then the message is described with placeholders", () => {
      expect(http_client.describe_request_error(new Error("something broke"))).toBe(
        "no error code something broke (resolved IP: unknown)"
      );
    });
  });

  describe("create_ip_recording_agent", () => {
    test("When the agent looks up a host name, Then the resolved address is recorded and passed on", () => {
      jest.spyOn(dns, "lookup").mockImplementation((hostname, options, callback) => {
        callback(null, "3.20.213.128", 4);
      });
      const agent = http_client.create_ip_recording_agent();
      const callback = jest.fn();

      agent.options.lookup("pulse3d.curibio.com", {}, callback);

      expect(agent.resolved_ip).toBe("3.20.213.128");
      expect(callback).toHaveBeenCalledWith(null, "3.20.213.128", 4);
    });
    test("When the agent looks up every address for a host name, Then all of the addresses are recorded", () => {
      const addresses = [
        { address: "3.20.213.128", family: 4 },
        { address: "18.226.38.203", family: 4 },
      ];
      jest.spyOn(dns, "lookup").mockImplementation((hostname, options, callback) => {
        callback(null, addresses);
      });
      const agent = http_client.create_ip_recording_agent();

      agent.options.lookup("pulse3d.curibio.com", { all: true }, jest.fn());

      expect(agent.resolved_ip).toBe("3.20.213.128, 18.226.38.203");
    });
  });
});
