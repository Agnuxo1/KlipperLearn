/* SPDX-License-Identifier: MIT. Open only the bundled functional reviewer. */
(function () {
  'use strict';
  const api = typeof browser !== 'undefined' ? browser : chrome;
  api.action.onClicked.addListener(() => {
    api.tabs.create({url: api.runtime.getURL('index.html')});
  });
}());
