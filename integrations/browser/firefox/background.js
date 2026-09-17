// SPDX-License-Identifier: GPL-3.0-or-later
browser.action.onClicked.addListener(() => {
  browser.tabs.create({url: browser.runtime.getURL('index.html')});
});
