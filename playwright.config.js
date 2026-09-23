// Drives the installed Google Chrome (channel) so no browser download is needed.
module.exports = { testDir: 'tests', timeout: 60000, use: { channel: 'chrome', headless: true, viewport: { width: 1280, height: 900 } }, reporter: 'list' };
