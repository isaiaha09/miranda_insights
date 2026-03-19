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

  async function refreshWidget(widget) {
    var refreshUrl = widget.dataset.refreshUrl;
    if (!refreshUrl) {
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

    workspace.querySelectorAll("form[data-client-workspace-form]").forEach(function (form) {
      form.addEventListener("submit", async function (event) {
        event.preventDefault();
        var submitButton = form.querySelector('button[type="submit"]');
        if (submitButton) {
          submitButton.disabled = true;
        }
        var response = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
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
        refreshWidget(widget).catch(function () {});
      });
    }

    var form = widget.querySelector("form[data-project-chat-form]");
    if (form) {
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