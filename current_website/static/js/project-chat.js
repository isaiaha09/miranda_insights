(function () {
  var widgetStates = new WeakMap();
  var keyboardInsetResetTimer = null;

  function getWidgetState(widget) {
    var state = widgetStates.get(widget);
    if (!state) {
      state = {
        requestToken: 0,
        isSubmitting: false,
      };
      widgetStates.set(widget, state);
    }
    return state;
  }

  function beginWidgetRequest(widget, options) {
    var state = getWidgetState(widget);
    state.requestToken += 1;
    if (options && options.submitting) {
      state.isSubmitting = true;
    }
    return state.requestToken;
  }

  function shouldApplyWidgetResponse(widget, token) {
    return document.body.contains(widget) && getWidgetState(widget).requestToken === token;
  }

  function finishWidgetRequest(widget, token, options) {
    if (!shouldApplyWidgetResponse(widget, token)) {
      return false;
    }
    if (options && options.submitting) {
      getWidgetState(widget).isSubmitting = false;
    }
    return true;
  }

  function isMobileChatViewport() {
    return window.matchMedia("(max-width: 800px)").matches;
  }

  function setKeyboardInset(value) {
    document.documentElement.style.setProperty("--project-chat-keyboard-inset", value + "px");
  }

  function getExpandedWidget() {
    return document.querySelector(".project-chat-widget-mobile-expanded");
  }

  function getExpandedComposerField() {
    var widget = getExpandedWidget();
    if (!widget) {
      return null;
    }
    return widget.querySelector('.project-chat-widget__composer .project-chat-widget__field textarea[name="body"]');
  }

  function updateKeyboardInset() {
    if (!document.body.classList.contains("project-chat-mobile-open") || !isMobileChatViewport()) {
      setKeyboardInset(0);
      return;
    }

    var visualViewport = window.visualViewport;
    if (!visualViewport) {
      setKeyboardInset(0);
      return;
    }

    var keyboardInset = Math.max(0, window.innerHeight - (visualViewport.height + visualViewport.offsetTop));
    setKeyboardInset(keyboardInset);

    if (keyboardInset > 0) {
      var composerField = getExpandedComposerField();
      if (composerField && document.activeElement === composerField) {
        window.requestAnimationFrame(function () {
          composerField.scrollIntoView({ block: "nearest" });
        });
      }
    }
  }

  function scheduleKeyboardInsetUpdate(delay) {
    window.clearTimeout(keyboardInsetResetTimer);
    keyboardInsetResetTimer = window.setTimeout(updateKeyboardInset, delay || 0);
  }

  function getMobileCloseButton() {
    var closeButton = document.querySelector("[data-chat-mobile-close]");
    if (closeButton) {
      return closeButton;
    }
    closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "project-chat-widget__mobile-close";
    closeButton.setAttribute("data-chat-mobile-close", "true");
    closeButton.setAttribute("aria-label", "Close expanded chat");
    closeButton.hidden = true;
    closeButton.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M6 6l12 12M18 6 6 18" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8"></path></svg>';
    closeButton.addEventListener("click", function () {
      document.querySelectorAll("[data-project-chat-widget]").forEach(function (widget) {
        setWidgetExpanded(widget, false);
      });
    });
    document.body.appendChild(closeButton);
    return closeButton;
  }

  function syncMobileCloseButton() {
    var closeButton = getMobileCloseButton();
    closeButton.hidden = !document.body.classList.contains("project-chat-mobile-open");
  }

  function setWidgetExpanded(widget, expanded) {
    if (!widget) {
      return;
    }
    var isExpanded = Boolean(expanded && isMobileChatViewport());
    var expandButton = widget.querySelector("[data-chat-expand-toggle]");
    var expandLabel = widget.querySelector("[data-chat-expand-label]");
    widget.classList.toggle("project-chat-widget-mobile-expanded", isExpanded);
    document.documentElement.classList.toggle("project-chat-mobile-open", isExpanded);
    document.body.classList.toggle("project-chat-mobile-open", isExpanded);
    if (expandButton) {
      expandButton.setAttribute("aria-expanded", isExpanded ? "true" : "false");
      expandButton.setAttribute("aria-label", isExpanded ? "Collapse chat" : "Expand chat");
    }
    if (expandLabel) {
      expandLabel.textContent = isExpanded ? "Close" : "Expand";
    }
    syncMobileCloseButton();
    if (!isExpanded) {
      setKeyboardInset(0);
    } else {
      scheduleKeyboardInsetUpdate(0);
    }
  }

  function syncExpandedWidget(widget) {
    setWidgetExpanded(widget, document.body.classList.contains("project-chat-mobile-open"));
  }

  function getCookie(name) {
    var cookieValue = null;
    if (!document.cookie) {
      return cookieValue;
    }
    document.cookie.split(";").forEach(function (cookie) {
      var trimmed = cookie.trim();
      if (trimmed.substring(0, name.length + 1) === name + "=") {
        cookieValue = decodeURIComponent(trimmed.substring(name.length + 1));
      }
    });
    return cookieValue;
  }

  function buildUrl(baseUrl, projectId) {
    var url = new URL(baseUrl, window.location.origin);
    if (projectId) {
      url.searchParams.set("project", projectId);
    }
    return url.toString();
  }

  function selectedProject(widget) {
    var select = widget.querySelector('select[name="project"]');
    return select ? select.value : "";
  }

  function hasDraftContent(form) {
    if (!form) {
      return false;
    }
    var messageField = form.querySelector('textarea[name="body"]');
    var fileInput = form.querySelector('.project-chat-widget__file-input');
    var linkInput = form.querySelector('[data-link-input]');
    return Boolean(
      (messageField && messageField.value.trim()) ||
      (fileInput && fileInput.files && fileInput.files.length) ||
      (linkInput && linkInput.value.trim())
    );
  }

  function isUserInteracting(widget) {
    if (!widget) {
      return false;
    }
    var active = document.activeElement;
    if (active && widget.contains(active)) {
      return true;
    }
    var form = widget.querySelector('form[data-project-chat-form]');
    return hasDraftContent(form);
  }

  function updateLinkStatus(form) {
    if (!form) {
      return;
    }
    var linkInput = form.querySelector('[data-link-input]');
    var linkStatus = form.querySelector('[data-link-status]');
    if (!linkInput || !linkStatus) {
      return;
    }
    linkStatus.textContent = linkInput.value.trim() ? 'Link ready to send' : 'No link added yet';
  }

  function replaceWidget(widget, html) {
    var wrapper = document.createElement("div");
    wrapper.innerHTML = html.trim();
    var nextWidget = wrapper.firstElementChild;
    if (!nextWidget) {
      return;
    }
    widget.replaceWith(nextWidget);
    initWidget(nextWidget);
  }

  function replaceWorkspace(workspace, html) {
    var wrapper = document.createElement("div");
    wrapper.innerHTML = html.trim();
    var nextWorkspace = wrapper.firstElementChild;
    if (!nextWorkspace) {
      return;
    }
    workspace.replaceWith(nextWorkspace);
    initWorkspace(nextWorkspace);
  }

  function syncConsultantCustomField(form) {
    if (!form) {
      return;
    }

    var consultantChoice = form.querySelector('[data-consultant-choice]');
    var customFieldWrapper = form.querySelector('[data-consultant-custom-field]');
    var customNameInput = form.querySelector('[data-consultant-custom-name]');

    if (!consultantChoice || !customFieldWrapper) {
      return;
    }

    var customOptionValue = consultantChoice.dataset.customConsultantOption || "";
    var showCustomField = consultantChoice.value === customOptionValue;

    customFieldWrapper.classList.toggle("is-hidden", !showCustomField);

    if (!showCustomField && customNameInput) {
      customNameInput.value = "";
    }
  }

  async function refreshWidget(widget, options) {
    options = options || {};
    var refreshUrl = widget.dataset.refreshUrl;
    var state = getWidgetState(widget);
    if (!refreshUrl || state.isSubmitting || (!options.force && isUserInteracting(widget))) {
      return;
    }
    var requestToken = beginWidgetRequest(widget);
    var response = await fetch(buildUrl(refreshUrl, selectedProject(widget)), {
      headers: { "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
    });
    if (!response.ok || !shouldApplyWidgetResponse(widget, requestToken)) {
      return;
    }
    replaceWidget(widget, await response.text());
  }

  function scheduleRefresh(widget) {
    window.setTimeout(function () {
      if (!document.body.contains(widget)) {
        return;
      }
      refreshWidget(widget).catch(function () {});
    }, 5000);
  }

  function initWorkspace(workspace) {
    if (!workspace || workspace.dataset.workspaceInitialized === "true") {
      return;
    }
    workspace.dataset.workspaceInitialized = "true";

    function buildWorkspaceFormData(container) {
      var formData = new FormData();

      container.querySelectorAll("input, select, textarea").forEach(function (field) {
        if (!field.name || field.disabled) {
          return;
        }

        if ((field.type === "checkbox" || field.type === "radio") && !field.checked) {
          return;
        }

        if (field.type === "file") {
          Array.prototype.forEach.call(field.files || [], function (file) {
            formData.append(field.name, file);
          });
          return;
        }

        formData.append(field.name, field.value);
      });

      return formData;
    }

    workspace.querySelectorAll("[data-client-workspace-form]").forEach(function (container) {
      syncConsultantCustomField(container);

      var consultantChoice = container.querySelector('[data-consultant-choice]');
      if (consultantChoice) {
        consultantChoice.addEventListener("change", function () {
          syncConsultantCustomField(container);
        });
      }

      var submitButton = container.querySelector('[data-client-workspace-submit]');
      if (!submitButton) {
        return;
      }

      submitButton.addEventListener("click", async function () {
        if (submitButton) {
          submitButton.disabled = true;
        }
        var response = await fetch(container.dataset.formAction, {
          method: "POST",
          body: buildWorkspaceFormData(container),
          headers: {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRFToken": getCookie("csrftoken") || "",
          },
          credentials: "same-origin",
        });
        if (!response.ok) {
          if (submitButton) {
            submitButton.disabled = false;
          }
          return;
        }
        replaceWorkspace(workspace, await response.text());
      });
    });
  }

  function initWidget(widget) {
    if (!widget || widget.dataset.chatInitialized === "true") {
      return;
    }
    widget.dataset.chatInitialized = "true";

    var select = widget.querySelector('select[name="project"]');
    if (select) {
      select.addEventListener("change", function () {
        refreshWidget(widget, { force: true }).catch(function () {});
      });
    }

    var expandButton = widget.querySelector("[data-chat-expand-toggle]");
    if (expandButton) {
      expandButton.addEventListener("click", function () {
        setWidgetExpanded(widget, !widget.classList.contains("project-chat-widget-mobile-expanded"));
      });
    }

    var form = widget.querySelector("form[data-project-chat-form]");
    if (form) {
      var fileInput = form.querySelector(".project-chat-widget__file-input");
      var fileName = form.querySelector("[data-file-name]");
      if (fileInput && fileName) {
        fileInput.addEventListener("change", function () {
          fileName.textContent = fileInput.files && fileInput.files.length ? "Attachment ready to send: " + fileInput.files[0].name : "No attachment selected yet";
        });
      }

      var linkToggle = form.querySelector("[data-link-toggle]");
      var linkPopover = form.querySelector("[data-link-popover]");
      var linkInput = form.querySelector("[data-link-input]");
      if (linkToggle && linkPopover && linkInput) {
        updateLinkStatus(form);
        linkInput.addEventListener("input", function () {
          updateLinkStatus(form);
        });
        linkToggle.addEventListener("click", function () {
          var isOpen = linkPopover.classList.toggle("is-open");
          linkToggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
          if (isOpen) {
            linkInput.focus();
          }
        });
      }

      form.addEventListener("submit", async function (event) {
        event.preventDefault();
        var widgetState = getWidgetState(widget);
        if (widgetState.isSubmitting) {
          return;
        }
        var submitButton = event.submitter || form.querySelector("[data-chat-submit-button]");
        var formData = new FormData(form);
        if (submitButton && submitButton.name) {
          formData.append(submitButton.name, submitButton.value);
        }
        if (submitButton && submitButton.dataset.confirmMessage && !window.confirm(submitButton.dataset.confirmMessage)) {
          return;
        }
        if (submitButton) {
          submitButton.disabled = true;
          if (submitButton.hasAttribute("data-chat-submit-button")) {
            submitButton.classList.add("is-loading");
          }
        }
        var requestToken = beginWidgetRequest(widget, { submitting: true });
        var response = await fetch(form.action, {
          method: "POST",
          body: formData,
          headers: { "X-Requested-With": "XMLHttpRequest" },
          credentials: "same-origin",
        });
        if (!response.ok) {
          finishWidgetRequest(widget, requestToken, { submitting: true });
          if (submitButton) {
            submitButton.disabled = false;
            submitButton.classList.remove("is-loading");
          }
          return;
        }
        if (!finishWidgetRequest(widget, requestToken, { submitting: true })) {
          return;
        }
        replaceWidget(widget, await response.text());
      });
    }

    var channel = widget.querySelector(".project-chat-widget__channel");
    if (channel) {
      channel.scrollTop = channel.scrollHeight;
    }
    syncExpandedWidget(widget);
    scheduleRefresh(widget);
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-project-chat-widget]").forEach(initWidget);
    document.querySelectorAll("[data-client-workspace]").forEach(initWorkspace);
    getMobileCloseButton();
    setKeyboardInset(0);
  });

  window.addEventListener("resize", function () {
    if (isMobileChatViewport()) {
      scheduleKeyboardInsetUpdate(0);
      return;
    }
    document.querySelectorAll("[data-project-chat-widget]").forEach(function (widget) {
      setWidgetExpanded(widget, false);
    });
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape" || !document.body.classList.contains("project-chat-mobile-open")) {
      return;
    }
    document.querySelectorAll("[data-project-chat-widget]").forEach(function (widget) {
      setWidgetExpanded(widget, false);
    });
  });

  document.addEventListener("focusin", function (event) {
    if (!event.target.matches('.project-chat-widget-mobile-expanded textarea[name="body"]')) {
      return;
    }
    scheduleKeyboardInsetUpdate(50);
  });

  document.addEventListener("focusout", function (event) {
    if (!event.target.matches('.project-chat-widget-mobile-expanded textarea[name="body"]')) {
      return;
    }
    scheduleKeyboardInsetUpdate(150);
  });

  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", updateKeyboardInset);
    window.visualViewport.addEventListener("scroll", updateKeyboardInset);
  }
})();