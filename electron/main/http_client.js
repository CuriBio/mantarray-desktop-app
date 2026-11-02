const axios = require("axios");
const dns = require("dns");
const https = require("https");

const DEFAULT_RETRIES = 3;
const MS_IN_SEC = 1000;
const DEFAULT_INITIAL_DELAY_MS = MS_IN_SEC * 3;
// making this 10 seconds to get around Windows' 21 second connection timeout
const DEFAULT_TIMEOUT_MS = MS_IN_SEC * 10;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const is_retryable = (error) =>
  !error.response || error.response.status >= 500 || error.response.status === 429;

/**
 * Create an HTTPS agent that records the IP address the host name resolved to, so a failed request can log
 * which address it tried to connect to. Timeout and certificate errors don't include it.
 *
 * @return {Object} an https.Agent whose `resolved_ip` property holds the most recently resolved address
 */
const create_ip_recording_agent = function () {
  const agent = new https.Agent({
    lookup: (hostname, options, callback) => {
      dns.lookup(hostname, options, (error, address, family) => {
        // address is an array of {address, family} objects when options.all is set
        agent.resolved_ip = Array.isArray(address)
          ? address.map((entry) => entry.address).join(", ")
          : address;
        callback(error, address, family);
      });
    },
  });
  return agent;
};

/**
 * Describe why a request failed in a form that is useful in the logs.
 *
 * @param {Object} error - the error raised by axios
 * @param {String} resolved_ip - the IP address the host name resolved to, if known
 *
 * @return {String} a short description of the failure
 */
const describe_request_error = function (error, resolved_ip) {
  const cause = error.response
    ? `HTTP ${error.response.status} ${error.response.statusText}`
    : `${error.code || "no error code"} ${error.message}`;
  return `${cause} (resolved IP: ${resolved_ip || "unknown"})`;
};

/**
 * Send a request with axios, retrying with exponential backoff if it fails
 * WARNING: Safe for GET, but double check if your call is idempotent for other verbs
 *
 * @param {Object} request_config - an axios request config, e.g. { url, method, data, headers, timeout }
 * @param {Object} options
 * @param {Number} options.retries - how many times to retry after the first attempt fails
 * @param {Number} options.initial_delay_ms - how long to wait before the first retry, doubled for each one after
 *
 * @return {Promise<Object>} the axios response from the first attempt that succeeds. Rejects with the error from
 * the last attempt, or from the first one that isn't worth retrying.
 */
const request_with_retry = async function (
  request_config,
  { retries = DEFAULT_RETRIES, initial_delay_ms = DEFAULT_INITIAL_DELAY_MS } = {}
) {
  const method = (request_config.method || "get").toUpperCase();
  // stripping off the querystring here incase there is sensitive info
  const request_description = `${method} ${request_config.url.split("?")[0]}`;
  const num_attempts = retries + 1;
  for (let attempt = 1; ; attempt++) {
    const agent = export_functions.create_ip_recording_agent();

    try {
      const response = await axios.request({
        timeout: DEFAULT_TIMEOUT_MS,
        httpsAgent: agent,
        ...request_config,
      });

      if (attempt > 1) {
        console.log(`${request_description} succeeded on attempt ${attempt} of ${num_attempts}`); // allow-log
      }

      return response;
    } catch (error) {
      console.log(
        // allow-log
        `${request_description} failed on attempt ${attempt} of ${num_attempts}: ` +
          describe_request_error(error, agent.resolved_ip)
      );

      if (attempt === num_attempts || !is_retryable(error)) {
        throw error;
      }

      // exponential backoff, doubling up each attempt
      await sleep(initial_delay_ms * 2 ** (attempt - 1));
    }
  }
};

// making spying/mocking with Jest easier. It's the same as utils.js
const export_functions = {
  create_ip_recording_agent,
  describe_request_error,
  request_with_retry,
};

export default export_functions;
