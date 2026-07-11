(function () {
  'use strict';

  var panelId = 'onboardingGuidePanel';
  var frameId = 'onboardingSpotlightFrame';
  var spotlightClass = 'onboarding-spotlight-target';
  var positionedClass = 'onboarding-spotlight-positioned';
  var activeBodyClass = 'onboarding-spotlight-active';
  var mobileQuery = '(max-width: 991.98px)';
  var currentTarget = null;
  var resizeTimer = null;
  var frameUpdateRequested = false;

  function getPanel() {
    return document.getElementById(panelId);
  }

  function isMobileViewport() {
    return window.matchMedia && window.matchMedia(mobileQuery).matches;
  }

  function getFallbackMessage(panel) {
    return panel ? panel.querySelector('[data-onboarding-spotlight-missing]') : null;
  }

  function setFallbackMessage(show) {
    var message = getFallbackMessage(getPanel());
    if (!message) {
      return;
    }
    message.classList.toggle('d-none', !show);
  }

  function getSpotlightFrame(create) {
    var frame = document.getElementById(frameId);
    if (!frame && create) {
      frame = document.createElement('div');
      frame.id = frameId;
      frame.className = 'onboarding-spotlight-frame';
      frame.setAttribute('aria-hidden', 'true');
      document.body.appendChild(frame);
    }
    return frame;
  }

  function removeSpotlightFrame() {
    var frame = getSpotlightFrame(false);
    if (frame) {
      frame.remove();
    }
  }

  function positionSpotlightFrame(target) {
    var frame = getSpotlightFrame(true);
    var rect = target.getBoundingClientRect();
    var padding = 8;
    var top = Math.max(8, rect.top - padding);
    var left = Math.max(8, rect.left - padding);
    var right = Math.min(window.innerWidth - 8, rect.right + padding);
    var bottom = Math.min(window.innerHeight - 8, rect.bottom + padding);

    frame.style.top = top + 'px';
    frame.style.left = left + 'px';
    frame.style.width = Math.max(0, right - left) + 'px';
    frame.style.height = Math.max(0, bottom - top) + 'px';
    frame.style.borderRadius = window.getComputedStyle(target).borderRadius || '0.5rem';
  }

  function requestSpotlightFrameUpdate() {
    if (!currentTarget || frameUpdateRequested) {
      return;
    }

    frameUpdateRequested = true;
    window.requestAnimationFrame(function () {
      frameUpdateRequested = false;
      if (currentTarget) {
        positionSpotlightFrame(currentTarget);
      }
    });
  }

  function isElementVisible(element) {
    if (!element || !element.getClientRects().length) {
      return false;
    }

    var style = window.getComputedStyle(element);
    if (
      style.display === 'none' ||
      style.visibility === 'hidden' ||
      Number(style.opacity) === 0
    ) {
      return false;
    }

    var rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function findSpotlightTarget(selector) {
    var panel = getPanel();
    var matches;

    try {
      matches = document.querySelectorAll(selector);
    } catch (error) {
      return null;
    }

    for (var index = 0; index < matches.length; index += 1) {
      if ((!panel || !panel.contains(matches[index])) && isElementVisible(matches[index])) {
        return matches[index];
      }
    }

    return null;
  }

  function resetTarget(element) {
    if (!element) {
      return;
    }
    element.classList.remove(spotlightClass);
    element.classList.remove(positionedClass);
  }

  function clearOnboardingSpotlight() {
    resetTarget(currentTarget);
    currentTarget = null;

    document.querySelectorAll('.' + spotlightClass).forEach(function (element) {
      resetTarget(element);
    });

    removeSpotlightFrame();
    document.body.classList.remove(activeBodyClass);
    setFallbackMessage(false);
  }

  function scrollTargetIntoView(target) {
    var rect = target.getBoundingClientRect();
    var topOffset = 84;
    var bottomOffset = 32;

    if (rect.top >= topOffset && rect.bottom <= window.innerHeight - bottomOffset) {
      return;
    }

    target.scrollIntoView({
      behavior: 'smooth',
      block: 'center',
      inline: 'nearest'
    });
  }

  function openOnboardingSpotlight(targetSelector) {
    clearOnboardingSpotlight();

    if (!targetSelector || isMobileViewport()) {
      return;
    }

    var target = findSpotlightTarget(targetSelector);
    if (!target) {
      setFallbackMessage(true);
      return;
    }

    if (window.getComputedStyle(target).position === 'static') {
      target.classList.add(positionedClass);
    }

    target.classList.add(spotlightClass);
    document.body.classList.add(activeBodyClass);
    currentTarget = target;
    positionSpotlightFrame(target);

    window.requestAnimationFrame(function () {
      scrollTargetIntoView(target);
      positionSpotlightFrame(target);
    });
  }

  function refreshOnboardingSpotlight() {
    var panel = getPanel();
    if (!panel || !panel.classList.contains('show')) {
      clearOnboardingSpotlight();
      return;
    }

    openOnboardingSpotlight(panel.dataset.currentTargetSelector || '');
  }

  function debouncedRefresh() {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(refreshOnboardingSpotlight, 120);
  }

  function bindOnboardingSpotlight() {
    var panel = getPanel();
    if (!panel) {
      return;
    }

    panel.addEventListener('shown.bs.offcanvas', refreshOnboardingSpotlight);
    panel.addEventListener('hide.bs.offcanvas', clearOnboardingSpotlight);
    panel.addEventListener('hidden.bs.offcanvas', clearOnboardingSpotlight);
    window.addEventListener('resize', debouncedRefresh);
    window.addEventListener('scroll', requestSpotlightFrameUpdate, true);

    if (panel.classList.contains('show')) {
      refreshOnboardingSpotlight();
    }
  }

  window.openOnboardingSpotlight = openOnboardingSpotlight;
  window.clearOnboardingSpotlight = clearOnboardingSpotlight;
  window.refreshOnboardingSpotlight = refreshOnboardingSpotlight;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindOnboardingSpotlight);
  } else {
    bindOnboardingSpotlight();
  }
})();
