(() => {
  'use strict';
  const root = document.querySelector('[data-scan-workflow]');
  const camera = root?.querySelector('[data-scan-camera]');
  if (!camera || !window.MotionmateParcelScan) return;
  const startButton = camera.querySelector('[data-camera-start]');
  const stopButton = camera.querySelector('[data-camera-stop]');
  const panel = camera.querySelector('[data-camera-panel]');
  const video = camera.querySelector('[data-camera-preview]');
  const status = camera.querySelector('[data-camera-status]');
  const formats = ['qr_code', 'code_128', 'code_39', 'ean_13', 'ean_8', 'upc_a', 'upc_e'];
  let generation = 0;
  let active = false;
  let stream = null;
  let decoder = null;
  let timer = null;
  let fallbackLoad = null;

  const say = message => { status.textContent = message; };
  const release = media => media?.getTracks().forEach(track => { if (track.readyState !== 'ended') track.stop(); });
  const stop = (message = 'Camera stopped. You can scan again or enter a tracking code.', focus = true) => {
    // Invalidate outstanding permission, playback and decode promises as well as timers.
    generation += 1;
    active = false;
    clearTimeout(timer);
    timer = null;
    release(stream);
    stream = null;
    video.pause();
    video.srcObject = null;
    decoder?.dispose();
    decoder = null;
    panel.hidden = true;
    startButton.setAttribute('aria-expanded', 'false');
    startButton.disabled = root.getAttribute('aria-busy') === 'true';
    say(message);
    if (focus) root.querySelector('[data-scan-input]').focus();
  };

  const loadFallback = () => {
    if (window.ZXingBrowser) return Promise.resolve(window.ZXingBrowser);
    if (fallbackLoad) return fallbackLoad;
    fallbackLoad = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      const timeout = setTimeout(() => failed(), 10000);
      const failed = () => {
        clearTimeout(timeout);
        script.remove();
        fallbackLoad = null;
        reject(new Error('decoder-unavailable'));
      };
      script.src = camera.dataset.decoderSrc;
      script.async = true;
      script.onload = () => {
        clearTimeout(timeout);
        if (window.ZXingBrowser) resolve(window.ZXingBrowser);
        else failed();
      };
      script.onerror = failed;
      document.head.append(script);
    });
    return fallbackLoad;
  };

  // Both implementations only decode local pixels. Neither resolves a Parcel,
  // owns a media stream, uploads frames or starts its own scan loop.
  const createDecoder = async () => {
    if (typeof window.BarcodeDetector?.getSupportedFormats === 'function') {
      try {
        const supported = await window.BarcodeDetector.getSupportedFormats();
        if (supported.includes('qr_code')) {
          const detector = new window.BarcodeDetector({formats: formats.filter(value => supported.includes(value))});
          return {detect: source => detector.detect(source), dispose() {}};
        }
      } catch {
        // Presence of the experimental API alone is not proof of usable QR support.
      }
    }
    const library = await loadFallback();
    let reader = new library.BrowserMultiFormatReader();
    reader.possibleFormats = ['QR_CODE', 'CODE_128', 'CODE_39', 'EAN_13', 'EAN_8', 'UPC_A', 'UPC_E']
      .map(name => library.BarcodeFormat[name]);
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('2d', {willReadFrequently: true});
    if (!context) throw new Error('decoder-unavailable');
    return {
      async detect(source) {
        const scale = Math.min(1, 960 / source.videoWidth);
        canvas.width = Math.round(source.videoWidth * scale);
        canvas.height = Math.round(source.videoHeight * scale);
        context.drawImage(source, 0, 0, canvas.width, canvas.height);
        try {
          return [{rawValue: reader.decodeFromCanvas(canvas).getText()}];
        } catch (error) {
          // ZXing's stable kind survives minification of exception class names.
          if (['NotFoundException', 'ChecksumException', 'FormatException'].includes(error.getKind?.())) return [];
          throw error;
        } finally {
          context.clearRect(0, 0, canvas.width, canvas.height);
        }
      },
      dispose() {
        canvas.width = canvas.height = 0;
        reader = null;
      },
    };
  };

  const errorMessage = error => {
    switch (error.name) {
      case 'NotAllowedError': case 'SecurityError':
        return 'Camera permission was denied. Allow camera access in your browser settings, or enter the tracking code.';
      case 'NotFoundError': case 'OverconstrainedError':
        return 'No usable camera was found. Connect a camera or enter the tracking code.';
      case 'NotReadableError': case 'AbortError':
        return 'The camera is unavailable or already in use. Close other camera apps and try again, or enter the tracking code.';
      default:
        return error.message === 'decoder-unavailable'
          ? 'Camera scanning is unavailable in this browser. Try another browser or enter the tracking code.'
          : 'Camera scanning could not continue. Try again or enter the tracking code.';
    }
  };

  const scanFrame = async token => {
    if (!active || token !== generation) return;
    try {
      if (video.readyState >= 2 && video.videoWidth) {
        const detected = await decoder.detect(video);
        if (!active || token !== generation) return;
        const isString = item => typeof item.rawValue === 'string';
        const code = detected.find(item => item.format === 'qr_code' && isString(item)) || detected.find(isString);
        if (code) {
          // Close and release before submission; one detection burst gets one attempt.
          stop('Code detected. Camera stopped. See the tracking code result below.', false);
          if (!window.MotionmateParcelScan.submitCode(code.rawValue)) {
            say('The code could not be submitted. Check the tracking code or connection below.');
          }
          return;
        }
      }
      if (active && token === generation) timer = setTimeout(() => scanFrame(token), 200);
    } catch (error) {
      if (active && token === generation) stop(errorMessage(error));
    }
  };

  const start = async () => {
    if (active || root.getAttribute('aria-busy') === 'true') return;
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      say('Camera access needs HTTPS and a supported browser. You can still enter the tracking code.');
      return;
    }
    if (!navigator.onLine) {
      say('A connection is required to look up parcels. Reconnect or enter the tracking code later.');
      return;
    }
    active = true;
    const token = ++generation;
    panel.hidden = false;
    startButton.disabled = true;
    startButton.setAttribute('aria-expanded', 'true');
    stopButton.focus();
    say('Preparing camera scanning…');
    let media = null;
    let adapter = null;
    try {
      adapter = await createDecoder();
      if (!active || token !== generation) { adapter.dispose(); return; }
      decoder = adapter;
      say('Waiting for camera permission. You can stop at any time.');
      try {
        media = await navigator.mediaDevices.getUserMedia({audio: false, video: {facingMode: {ideal: 'environment'}}});
      } catch (error) {
        if (error.name !== 'OverconstrainedError' || !active || token !== generation) throw error;
        // Devices without a rear camera may still provide a usable front camera.
        media = await navigator.mediaDevices.getUserMedia({audio: false, video: true});
      }
      if (!active || token !== generation) { release(media); return; }
      stream = media;
      stream.getVideoTracks().forEach(track => track.addEventListener('ended', () => {
        if (active && token === generation) stop('Camera disconnected. Try again or enter the tracking code.');
      }, {once: true}));
      video.srcObject = stream;
      await video.play();
      if (!active || token !== generation) return;
      say('Scanning… Hold the tracking code steady, or stop and enter it manually.');
      scanFrame(token);
    } catch (error) {
      if (active && token === generation) stop(errorMessage(error));
      else release(media);
    }
  };

  camera.hidden = false;
  startButton.addEventListener('click', start);
  stopButton.addEventListener('click', () => stop());
  document.addEventListener('keydown', event => {
    if (active && event.key === 'Escape') { event.preventDefault(); stop(); }
  });
  // Manual submissions and operational actions never leave a competing camera running.
  root.addEventListener('submit', () => { if (active) stop(); }, true);
  root.querySelector('[data-next-scan]').addEventListener('click', () => { if (active) stop(); });
  new MutationObserver(() => {
    if (active && panel.hidden) stop();
  }).observe(panel, {attributes: true, attributeFilter: ['hidden']});
  window.addEventListener('pagehide', () => stop('Camera stopped.', false));
  document.addEventListener('visibilitychange', () => {
    if (active && document.hidden) stop('Camera stopped while the page was hidden.', false);
  });
})();
