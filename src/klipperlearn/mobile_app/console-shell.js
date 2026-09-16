(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const storageKey = 'klipperlearn-console-preferences-v4';
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(storageKey) || '{}') || {}; } catch (_) {}
  const preferences = {
    sound: typeof saved.sound === 'boolean' ? saved.sound : true,
    volume: Number.isFinite(saved.volume) ? Math.max(0, Math.min(100, saved.volume)) : 30,
    welcome: typeof saved.welcome === 'boolean' ? saved.welcome : true
  };
  let audioContext = null, master = null, audioEpoch = 0;
  const returnFocus = new WeakMap();

  function savePreferences() {
    try { localStorage.setItem(storageKey, JSON.stringify(preferences)); } catch (_) {}
  }
  function renderPreferences() {
    $('soundEnabled').checked = preferences.sound;
    $('soundVolume').value = String(preferences.volume);
    $('volumeReading').value = preferences.volume + ' %';
    $('welcomeEnabled').checked = preferences.welcome;
    if (master && audioContext) master.gain.setValueAtTime(preferences.sound ? preferences.volume / 100 * 0.16 : 0, audioContext.currentTime);
  }
  function mute() {
    audioEpoch++;
    preferences.sound = false;
    renderPreferences();
    savePreferences();
  }

  // Original synthesized motif. Every oscillator stops; no recording or audio files.
  function playSound(welcome = false) {
    if (!preferences.sound || preferences.volume === 0) return;
    const epoch = audioEpoch;
    try {
      const Audio = window.AudioContext || window.webkitAudioContext;
      if (!Audio) return;
      if (!audioContext) {
        audioContext = new Audio();
        master = audioContext.createGain();
        master.connect(audioContext.destination);
      }
      renderPreferences();
      Promise.resolve(audioContext.resume()).then(() => {
        if (!preferences.sound || epoch !== audioEpoch || audioContext.state !== 'running') return;
        const notes = welcome ? [[440, 0, .14], [587.33, .12, .13], [659.25, .25, .14], [880, .40, .26]] : [[680, 0, .045]];
        const start = audioContext.currentTime;
        notes.forEach(([frequency, offset, duration]) => {
          const oscillator = audioContext.createOscillator();
          const envelope = audioContext.createGain();
          oscillator.type = 'sine';
          oscillator.frequency.value = frequency;
          envelope.gain.setValueAtTime(0, start + offset);
          envelope.gain.linearRampToValueAtTime(.7, start + offset + .009);
          envelope.gain.exponentialRampToValueAtTime(.001, start + offset + duration);
          oscillator.connect(envelope);
          envelope.connect(master);
          oscillator.start(start + offset);
          oscillator.stop(start + offset + duration + .01);
          oscillator.onended = () => { oscillator.disconnect(); envelope.disconnect(); };
        });
      }).catch(() => {});
    } catch (_) {
      // Audio is optional: a denied autoplay never blocks entry or controls.
    }
  }

  function openDialog(id) {
    const dialog = $(id);
    if (!dialog || dialog.open) return;
    returnFocus.set(dialog, document.activeElement);
    dialog.showModal();
  }
  function closeDialog(dialog) {
    if (dialog && dialog.open) dialog.close();
  }
  document.querySelectorAll('dialog').forEach(dialog => {
    dialog.addEventListener('click', event => {
      if (event.target !== dialog) return;
      const rect = dialog.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closeDialog(dialog);
    });
    dialog.addEventListener('close', () => {
      const previous = returnFocus.get(dialog);
      if (previous && previous.isConnected && !previous.disabled) previous.focus();
    });
  });

  function confirmAction(message) {
    const dialog = $('confirmDialog');
    if (dialog.open) return Promise.resolve(false);
    $('confirmMessage').textContent = message;
    let accepted = false;
    return new Promise(resolve => {
      const accept = () => { accepted = true; closeDialog(dialog); };
      const finish = () => {
        $('confirmAccept').removeEventListener('click', accept);
        resolve(accepted);
      };
      $('confirmAccept').addEventListener('click', accept);
      dialog.addEventListener('close', finish, {once: true});
      openDialog('confirmDialog');
    });
  }

  function switchView(name) {
    if (!['printer', 'files', 'camera', 'calibration'].includes(name)) return;
    document.querySelectorAll('.view').forEach(view => { view.hidden = view.id !== 'view-' + name; });
    document.querySelectorAll('[data-view]').forEach(button => {
      if (button.dataset.view === name) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
    // Hide panels only. The camera's video node and stream remain mounted.
    document.dispatchEvent(new CustomEvent('console:view', {detail: name}));
  }

  document.addEventListener('click', event => {
    const capture = event.target.closest('[data-capture]');
    if (capture) { mute(); return; }
    const button = event.target.closest('button');
    if (!button || button.disabled) return;
    if (!['enterWelcome', 'enterSilent'].includes(button.id)) playSound();
    if (button.dataset.view) switchView(button.dataset.view);
    if (button.dataset.dialog) openDialog(button.dataset.dialog);
    if (button.hasAttribute('data-close')) closeDialog(button.closest('dialog'));
  }, true);

  $('soundEnabled').addEventListener('change', () => {
    audioEpoch++;
    preferences.sound = $('soundEnabled').checked;
    renderPreferences(); savePreferences();
  });
  $('soundVolume').addEventListener('input', () => {
    preferences.volume = Number($('soundVolume').value);
    renderPreferences(); savePreferences();
  });
  $('welcomeEnabled').addEventListener('change', () => {
    preferences.welcome = $('welcomeEnabled').checked;
    savePreferences();
  });
  $('enterWelcome').addEventListener('click', () => {
    playSound(true);
    closeDialog($('welcomeDialog'));
    document.dispatchEvent(new Event('console:activate'));
  });
  $('enterSilent').addEventListener('click', () => {
    mute();
    closeDialog($('welcomeDialog'));
    document.dispatchEvent(new Event('console:activate'));
  });
  $('fullscreen').addEventListener('click', async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else if (document.documentElement.requestFullscreen) await document.documentElement.requestFullscreen();
      else throw Error();
      $('settingsStatus').textContent = '';
    } catch (_) { $('settingsStatus').textContent = "Full screen is unavailable."; }
  });
  document.addEventListener('fullscreenchange', () => {
    $('fullscreen').textContent = document.fullscreenElement ? "Exit full screen" : "Full screen";
  });
  document.querySelectorAll('img[src="klipper-logo.svg"]').forEach(img => {
    img.addEventListener('error', () => { img.style.visibility = 'hidden'; });
  });
  window.ConsoleShell = Object.freeze({confirm: confirmAction, openDialog, closeDialog, mute});
  renderPreferences();
  if (preferences.welcome) openDialog('welcomeDialog');
})();
