/** @type {import('@commitlint/types').UserConfig} */
export default {
  extends: ["@commitlint/config-conventional"],
  ignores: [
    (message) => message.startsWith("Merge "),
    (message) => /^release: /i.test(message),
    // Dependabot's "Bump ..." subjects and long changelog bodies don't follow the config.
    (message) => /^Signed-off-by: dependabot\[bot\]/m.test(message),
  ],
};
