(function () {
  "use strict";

  function initializeNewsletterCampaignForm() {
    var modeInput = document.getElementById("id_mode");
    var frequencyInput = document.getElementById("id_frequency");
    var automatedSections = document.querySelectorAll(".newsletter-automated-settings");
    var customSections = document.querySelectorAll(".newsletter-custom-settings");

    if (!modeInput || (!automatedSections.length && !customSections.length)) {
      return;
    }

    function updateVisibility() {
      var isAutomated = modeInput.value === "automated";

      automatedSections.forEach(function (section) {
        section.hidden = !isAutomated;
        section.setAttribute("aria-hidden", isAutomated ? "false" : "true");
      });
      customSections.forEach(function (section) {
        section.hidden = isAutomated;
        section.setAttribute("aria-hidden", isAutomated ? "true" : "false");
      });

      var selectedFrequency = frequencyInput ? frequencyInput.value : "";
      ["interval", "weekly", "monthly"].forEach(function (frequency) {
        document.querySelectorAll(".newsletter-frequency-" + frequency).forEach(function (section) {
          var isVisible = isAutomated && selectedFrequency === frequency;
          section.hidden = !isVisible;
          section.setAttribute("aria-hidden", isVisible ? "false" : "true");
        });
      });
    }

    modeInput.addEventListener("change", updateVisibility);
    if (frequencyInput) {
      frequencyInput.addEventListener("change", updateVisibility);
    }
    updateVisibility();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializeNewsletterCampaignForm);
  } else {
    initializeNewsletterCampaignForm();
  }
})();
