const axios = require("axios");
const axiosRetry = require("axios-retry").default;

const MS_IN_SEC = 1000;
// making this 10 seconds to get around Windows' 21 second connection timeout
const TIMEOUT_MS = MS_IN_SEC * 10;
const RETRIES = 4;
// axios-retry doubles this before the first retry, so the waits are about 5s, 10s, 20s, 40s (plus up to 20% jitter)
const RETRY_DELAY_FACTOR_MS = MS_IN_SEC * 2.5;

/**
 * Decide whether a failed request to the cloud should be sent again. axios-retry's default condition
 * doesn't retry timeouts (ECONNABORTED) or DNS failures (ENOTFOUND), which are the main failures we want to
 * retry, so this replaces it. Only GETs are retried since a request that timed out may still have reached
 * the server.
 *
 * @param {Object} error - the error raised by axios
 *
 * @return {Boolean} true if the request should be retried
 */
const should_retry = (error) =>
  error.config.method === "get" &&
  (!error.response || error.response.status >= 500 || error.response.status === 429);

// only use this for cloud requests. Requests to the local Flask server should keep using axios directly
const cloud_client = axios.create({ timeout: TIMEOUT_MS });
axiosRetry(cloud_client, {
  retries: RETRIES,
  retryCondition: should_retry,
  retryDelay: (retry_count, error) => axiosRetry.exponentialDelay(retry_count, error, RETRY_DELAY_FACTOR_MS),
  // give each attempt its own timeout instead of sharing one timeout across every attempt
  shouldResetTimeout: true,
  onRetry: (retry_count, error, request_config) => {
    console.log(`Retry ${retry_count} of ${RETRIES} for ${request_config.url} after: ${error.message}`); // allow-log
  },
});

export default { cloud_client };
