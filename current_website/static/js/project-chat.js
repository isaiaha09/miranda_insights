(function () {
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
    if (!refreshUrl || (!options.force && isUserInteracting(widget))) {
      return;
    }
    var response = await fetch(buildUrl(refreshUrl, selectedProject(widget)), {
      headers: { "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
    });
    if (!response.ok) {
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
        var submitButton = form.querySelector("[data-chat-submit-button]");
        if (submitButton) {
          submitButton.disabled = true;
          submitButton.classList.add("is-loading");
        }
        var response = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          headers: { "X-Requested-With": "XMLHttpRequest" },
          credentials: "same-origin",
        });
        if (!response.ok) {
          if (submitButton) {
            submitButton.disabled = false;
            submitButton.classList.remove("is-loading");
          }
          return;
        }
        replaceWidget(widget, await response.text());
      });
    }

    var channel = widget.querySelector(".project-chat-widget__channel");
    if (channel) {
      channel.scrollTop = channel.scrollHeight;
    }
    scheduleRefresh(widget);
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-project-chat-widget]").forEach(initWidget);
    document.querySelectorAll("[data-client-workspace]").forEach(initWorkspace);
  });
})();