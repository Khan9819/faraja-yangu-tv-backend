/**
 * video-ad-player.js — Faraja Yangu TV Web Player (hard-gate ad system)
 * ---------------------------------------------------------------------
 * Player wa web kwa ajili ya watumiaji wa iPhone wasioweza kupakua App ya
 * Android. Inatumia video.js + Google IMA SDK + videojs-ima.
 *
 * Mfumo wa "hard gate":
 *   - Mtumiaji HAIWEZI kuona content (video) mpaka pre-roll pod ikamilike.
 *   - Mid-roll ads huchezwa kila baada ya dakika 10 (au kama VMAP tag
 *     inatoa mid-rolls zake, hizo ndizo zinatumika).
 *   - HAKUNA "Skip Ad" button (imefichwa kwenye CSS ya template).
 *   - Kama matangazo yanashindikana (VAST error), content huendelea
 *     kuchezwa moja kwa moja — hatumzuii mtumiaji milele.
 *
 * Njia rasmi ya gate: tunasikiliza CONTENT_PAUSE_REQUESTED na
 * CONTENT_RESUME_REQUESTED (google.ima.AdEvent.Type) — IMA SDK ndiyo
 * inayodhibiti content kuonekana/kufichwa wakati wa ad breaks.
 * ---------------------------------------------------------------------
 */
(function () {
  'use strict';

  /* ================================================================
   * TODO: Badilisha na VAST/VMAP tag halisi ukishaidhinishwa
   *       AdSense / Google Ad Manager (GAM).
   *
   * Hii ni VMAP sample ya Google (ad rules: pre + mid + post) kwa
   * ajili ya testing pekee. Ukishapata tag yako halisi, badilisha
   * AD_TAG_URL hapa (line 31 ya file hii).
   * ================================================================ */
  var AD_TAG_URL =
    'https://pubads.g.doubleclick.net/gampad/ads?iu=/21775744923/external/ad_rule_samples' +
    '&sz=640x480&ciu_szs=300x250&gdfp_req=1&ad_rule=1&output=vmap' +
    '&unviewed_position_start=1&env=vp&impl=s' +
    '&cust_params=deployment%3Ddevsite%26sample_ar%3Dpremidpost';

  // Mid-roll huchezwa kila baada ya dakika 10 (sekunde 600).
  // Hii ni FALLBACK tu — kama VMAP tag halisi ina mid-rolls zake,
  // hizo ndizo zinatakiwa. Inatumika pale tag haina mid-rolls.
  var MIDROLL_INTERVAL_SECONDS = 600;

  // Muda wa kusubiri kabla ya kuamini ads hazijapakia (watchdog).
  var AD_WATCHDOG_MS = 8000;

  var config = window.FARAJATV_CONFIG || {};
  var player = null;

  var gateOverlay = document.getElementById('gate-overlay');
  var startBtn = document.getElementById('start-btn');
  var adBadge = document.getElementById('ad-badge');
  var adBadgeText = document.getElementById('ad-badge-text');
  var adBadgeSpinner = document.getElementById('ad-badge-spinner');
  var shareBtn = document.getElementById('share-btn');
  var shareFeedback = document.getElementById('share-feedback');

  var playbackRequested = false; // mtumiaji amebofya "Bofya kuanza"
  var imaAvailable = false;     // videojs-ima plugin imepakia vizuri?
  var adWatchdog = null;

  /* ----------------------------------------------------------------
   * UI helpers
   * ---------------------------------------------------------------- */
  function showAdBadge(message) {
    adBadge.classList.remove('is-hidden');
    adBadgeText.textContent = message || 'Inaandaa matangazo...';
    if (adBadgeSpinner) adBadgeSpinner.classList.remove('is-hidden');
  }

  function hideAdBadge() {
    adBadge.classList.add('is-hidden');
  }

  function showGate() {
    gateOverlay.classList.remove('is-hidden');
  }

  function hideGate() {
    gateOverlay.classList.add('is-hidden');
  }

  /* ----------------------------------------------------------------
   * HARD GATE — handlers rasmi za IMA SDK (CONTENT_PAUSE/RESUME)
   * ---------------------------------------------------------------- */

  // CONTENT_PAUSE_REQUESTED: ad break inaanza → content inafungwa.
  // Tunabadilisha badge kuhimiza "Ad N of M" ya pod hiyo.
  // (Content yenyewe inasitishwa na IMA SDK — ad container inafunika video.)
  function onImaContentPause() {
    showAdBadge('Matangazo yanaendelea...');
  }

  // CONTENT_RESUME_REQUESTED: ad break imekamilika → content inarudi.
  // Hii ndiyo inayofungua "gate" ya pre-roll na mid-rolls.
  function onImaContentResume() {
    hideAdBadge();
    clearWatchdog();
  }

  // ALL_ADS_COMPLETED: ad experience nzima imekamilika.
  function onImaAllAdsCompleted() {
    hideAdBadge();
    clearWatchdog();
  }

  // AD_ERROR: VAST/VMAP imeshindikana → content iendelee moja kwa moja
  // (usimzuie mtumiaji milele). Hii ndiyo default behavior ya IMA SDK.
  function onImaAdError() {
    hideAdBadge();
    clearWatchdog();
    // Hakikisha content inacheza (kama haijaanza bado).
    if (playbackRequested && player) {
      try { player.play(); } catch (err) { /* noop */ }
    }
  }

  /* ----------------------------------------------------------------
   * Mid-roll fallback: kila dakika 10 (kama tag haina mid-rolls)
   * ---------------------------------------------------------------- */
  function ensureMidRollCuePoints(adsManager) {
    try {
      var cuePoints = (typeof adsManager.getCuePoints === 'function')
        ? (adsManager.getCuePoints() || [])
        : [];

      // Cue points za VMAP: pre-roll = 0, mid-rolls = nyakati (sekunde),
      // post-roll = -1. Tunaangalia kama zipo mid-rolls.
      var hasMidRoll = cuePoints.some(function (t) {
        return typeof t === 'number' && t > 0 && t < config.durationSeconds;
      });

      if (!hasMidRoll &&
          config.durationSeconds > MIDROLL_INTERVAL_SECONDS &&
          typeof adsManager.addCuePoints === 'function') {
        var points = [];
        for (var t = MIDROLL_INTERVAL_SECONDS;
             t < config.durationSeconds - 60;
             t += MIDROLL_INTERVAL_SECONDS) {
          points.push({ startTime: t, endTime: t });
        }
        if (points.length) {
          adsManager.addCuePoints(points);
          console.log('[FarajaTV] Mid-roll cue points zimeongezwa: ' +
            points.length + ' kwenye sekunde za kila ' +
            MIDROLL_INTERVAL_SECONDS + 's');
        }
      }
    } catch (err) {
      console.warn('[FarajaTV] ensureMidRollCuePoints failed:', err);
    }
  }

  /* ----------------------------------------------------------------
   * AdsManager loaded → attach rasmi CONTENT_PAUSE/RESUME listeners
   * ---------------------------------------------------------------- */
  function onAdsManagerLoaded(adsManager) {
    if (!adsManager) return;
    try {
      // Hizi ndizo events rasmi za IMA SDK zinazodhibiti "gate".
      // (Zinapatikana kwenye google.ima.AdEvent.Type)
      adsManager.addEventListener(
        google.ima.AdEvent.Type.CONTENT_PAUSE_REQUESTED, onImaContentPause);
      adsManager.addEventListener(
        google.ima.AdEvent.Type.CONTENT_RESUME_REQUESTED, onImaContentResume);
      adsManager.addEventListener(
        google.ima.AdEvent.Type.ALL_ADS_COMPLETED, onImaAllAdsCompleted);
      adsManager.addEventListener(
        google.ima.AdEvent.Type.AD_ERROR, onImaAdError);
    } catch (err) {
      console.warn('[FarajaTV] Kuna tatizo kuattach IMA listeners:', err);
    }

    ensureMidRollCuePoints(adsManager);
  }

  /* ----------------------------------------------------------------
   * Ad counter: "Tangazo 1 kati ya 3" (kutoka AdPodInfo)
   * ---------------------------------------------------------------- */
  function onAdStarted() {
    try {
      var ad = player.ima.getCurrentAd ? player.ima.getCurrentAd() : null;
      var pod = ad && typeof ad.getAdPodInfo === 'function'
        ? ad.getAdPodInfo() : null;
      if (pod) {
        var position = pod.getAdPosition();
        var total = pod.getTotalAds();
        if (position > 0 && total > 0) {
          showAdBadge('Tangazo ' + position + ' kati ya ' + total);
        }
      }
    } catch (err) {
      showAdBadge('Matangazo yanaendelea...');
    }
  }

  /* ----------------------------------------------------------------
   * Watchdog: kama ads hazijapakia (VAST timeout / block), content
   * inacheza moja kwa moja — tusimzuie mtumiaji milele.
   * ---------------------------------------------------------------- */
  function armWatchdog() {
    clearWatchdog();
    adWatchdog = setTimeout(function () {
      console.warn('[FarajaTV] Ads hazikupakia kwa wakati — content inaendelea.');
      if (player) {
        try { player.play(); } catch (err) { /* noop */ }
      }
      onImaAdError();
    }, AD_WATCHDOG_MS);
  }

  function clearWatchdog() {
    if (adWatchdog) {
      clearTimeout(adWatchdog);
      adWatchdog = null;
    }
  }

  /* ----------------------------------------------------------------
   * Start playback — hii ni user gesture (inahitajika na Safari/iOS
   * kwa autoplay policies. Hakuna autoplay ya moja kwa moja).
   * ---------------------------------------------------------------- */
  function startPlayback() {
    if (!player || playbackRequested) return;
    playbackRequested = true;

    hideGate();
    hidePlayerError();

    // videojs-ima haijapakia (au IMA imeharibika) → cheza content tu.
    if (!imaAvailable) {
      try { player.play(); } catch (err) { /* noop */ }
      return;
    }

    showAdBadge('Inaandaa matangazo...');
    armWatchdog();

    try {
      // initializeAdDisplayContainer lazima iwe ndani ya user action
      // (kwa mobile/Safari) — ndiyo maana tumeiweka hapa.
      player.ima.initializeAdDisplayContainer();
      player.ima.setContentWithAdTag(null, AD_TAG_URL, false);
      player.ima.requestAds();
      player.play();
    } catch (err) {
      console.error('[FarajaTV] Kushindwa kuanzisha ads:', err);
      // Kosa lolote → content icheze bila ads.
      onImaAdError();
      try { player.play(); } catch (e) { /* noop */ }
    }
  }

  /* ----------------------------------------------------------------
   * Share button — nakili kiungo cha video
   * ---------------------------------------------------------------- */
  function initShare() {
    if (!shareBtn) return;
    shareBtn.addEventListener('click', function () {
      var url = window.location.href;
      var done = function () {
        shareFeedback.classList.add('is-visible');
        setTimeout(function () {
          shareFeedback.classList.remove('is-visible');
        }, 2200);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(done).catch(function () {
          fallbackCopy(url);
          done();
        });
      } else {
        fallbackCopy(url);
        done();
      }
    });
  }

  function fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch (e) { /* noop */ }
    document.body.removeChild(ta);
  }

  /* ----------------------------------------------------------------
   * Branded error state (badala ya modal ya default ya video.js)
   * ---------------------------------------------------------------- */
  var errorOverlay = null;

  function showPlayerError(message) {
    if (!errorOverlay) {
      errorOverlay = document.createElement('div');
      errorOverlay.id = 'player-error-overlay';
      errorOverlay.innerHTML =
        '<div class="err-content">' +
          '<div class="err-icon">⚠</div>' +
          '<p class="err-title">Video haiwezi kuchezwa</p>' +
          '<p class="err-msg"></p>' +
          '<button type="button" class="err-btn" id="err-retry">Jaribu tena</button>' +
        '</div>';
      document.getElementById('player-wrap').appendChild(errorOverlay);
      errorOverlay.querySelector('#err-retry').addEventListener('click', function () {
        errorOverlay.classList.add('is-hidden');
        if (player) {
          try { player.load(); player.play(); } catch (e) { /* noop */ }
        }
      });
    }
    var msgEl = errorOverlay.querySelector('.err-msg');
    if (msgEl) msgEl.textContent = message || '';
    errorOverlay.classList.remove('is-hidden');
  }

  function hidePlayerError() {
    if (errorOverlay) errorOverlay.classList.add('is-hidden');
  }

  /* ----------------------------------------------------------------
   * Download protection — zuia njia za kawaida za kuhifadhi video:
   * right-click "Save video as", drag-drop, na download buttons.
   * (Hii ni client-side tu — server-side inatumia signed expiring URLs
   * kukataa IDM na ufikiaji wa moja kwa moja kwenye HLS files.)
   * ---------------------------------------------------------------- */
  function initDownloadProtection() {
    var wrap = document.getElementById('player-wrap');
    if (!wrap) return;

    // Context menu: zuia kwenye video na control bar ("Save video as..."),
    // lakini acha vitufe/links (share, close, app CTA) zifanye kazi.
    wrap.addEventListener('contextmenu', function (e) {
      var t = e.target;
      if (t && (t.tagName === 'VIDEO' || (t.closest && t.closest('.vjs-control-bar')))) {
        e.preventDefault();
      }
    });

    // Drag-drop ya video (kuhifadhi kwa kuburuta kwenye desktop).
    wrap.addEventListener('dragstart', function (e) {
      e.preventDefault();
    });
    wrap.addEventListener('drop', function (e) {
      e.preventDefault();
    });

    // Ondoa kitufe cha download kama video.js kitawasha wakati wowote.
    var unblockDownload = function () {
      try {
        if (player && player.controlBar) {
          var dl = player.controlBar.getChild('downloadButton');
          if (dl) player.controlBar.removeChild(dl);
        }
      } catch (err) { /* noop */ }
    };
    unblockDownload();
    if (player) {
      player.on('loadedmetadata', unblockDownload);
    }
  }

  /* ----------------------------------------------------------------
   * Init
   * ---------------------------------------------------------------- */
  function init() {
    if (!config.streamUrl) {
      // Hakuna video — onyesha gate tu kama fallback ya UI.
      showGate();
      return;
    }

    player = videojs('content_video', {
      autoplay: false,               // Safari/iOS: user gesture tu
      controls: true,
      fluid: true,
      responsive: true,
      nativeControlsForTouch: false,
      playsinline: true,
      preload: 'auto',
      poster: config.cover || '',
      sources: [{ src: config.streamUrl, type: 'application/x-mpegURL' }]
    });

    // videojs-ima v2 — adsManagerLoadedCallback ndiyo njia rasmi ya
    // kupata adsManager (badala ya ku-subscribe 'ads-manager' event).
    // Ikiwa plugin haijapakia (CDN/static failure), tumia player bila ads
    // badala ya kuvunja player nzima.
    try {
      player.ima({
        adLabel: 'Tangazo',
        showCountdown: true,
        disableAdControls: false,
        adsManagerLoadedCallback: onAdsManagerLoaded
      });
      imaAvailable = true;
    } catch (err) {
      imaAvailable = false;
      console.warn('[FarajaTV] videojs-ima haijapakia — content itacheza bila ads.', err);
    }

    if (imaAvailable) {
      // Ad lifecycle event za plugin (counter ya "Ad N of M").
      player.on('ads-ad-started', onAdStarted);
    }

    // Ondoa Settings menu (gear) — "name tabs" dropdown ya quality inayoonekana
    // kama dropbox. Quality inabadilika moja kwa moja (Auto) kupitia VHS.
    try {
      if (player.controlBar) {
        var settingsBtn = player.controlBar.getChild('settingsMenuButton');
        if (settingsBtn) {
          player.controlBar.removeChild(settingsBtn);
        }
      }
    } catch (err) { /* noop */ }

    // Ikiwa content yenyewe ina error (HLS), ficha badge na onyesha
    // ujumbe wa kirafiki (badala ya modal ya default ya video.js).
    player.on('error', function () {
      hideAdBadge();
      var err = player.error ? player.error() : null;
      showPlayerError(
        'Video imeshindwa kucheza. Tafadhali angalia mtandao wako na jaribu tena.' +
        (err && err.code === 4 ? ' (Stream haikupatikana)' : '')
      );
    });

    // Start button — safari: lazima user gesture.
    if (startBtn) {
      startBtn.addEventListener('click', startPlayback);
      startBtn.addEventListener('touchend', function (e) {
        e.preventDefault();
        startPlayback();
      });
    }

    initDownloadProtection();
    initShare();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
