/**
 * Get the current timestamp
 * @returns {string}
 */
function getCurrentTimestamp() {
  return new Date().toISOString().replace('T', ' ').slice(0, 23);
}

/**
 * Get the duration between the current time and the start time
 * @param {number} startTime - The start time
 * @returns {number} - The duration in seconds
 */
function getDuration(startTime) {
  return (Date.now() - startTime) / 1000;
}

/**
 * Get the oldest date from an array of dates
 * @param {Date[]} dates - Array of Date objects
 * @returns {Date|undefined} - The oldest date if array is not empty, undefined otherwise
 */
function getOldestDate(dates) {
  return dates.length > 0 ? new Date(Math.min(...dates.map(date => date.getTime()))) : undefined;
}

/**
 * Get the most recent date from an array of dates
 * @param {Date[]} dates - Array of Date objects
 * @returns {Date|undefined} - The most recent date if array is not empty, undefined otherwise
 */
function getMostRecentDate(dates) {
  return dates.length > 0 ? new Date(Math.max(...dates.map(date => date.getTime()))) : undefined;
}

export default {
  getCurrentTimestamp,
  getDuration,
  getOldestDate,
  getMostRecentDate
};
