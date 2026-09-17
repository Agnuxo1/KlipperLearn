// SPDX-License-Identifier: GPL-3.0-or-later
// Open only the packaged workspace; no privileged tabs or site permission is needed.
chrome.action.onClicked.addListener(() => {
  chrome.tabs.create({url: chrome.runtime.getURL('index.html')});
});
