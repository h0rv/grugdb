(() => {
  const root = document.documentElement;
  const preference = window.matchMedia("(prefers-color-scheme: dark)");
  let saved = null;
  try { saved = localStorage.getItem("grugdb-theme"); } catch {}
  if (saved === "dark" || saved === "light") root.dataset.theme = saved;

  const dark = () => root.dataset.theme
    ? root.dataset.theme === "dark"
    : preference.matches;

  document.addEventListener("DOMContentLoaded", () => {
    const theme = document.getElementById("theme");
    if (window.matchMedia("(max-width: 760px)").matches) {
      document.querySelector(".contents").open = false;
    }
    const label = () => {
      const next = dark() ? "light" : "dark";
      theme.title = `Switch to ${next} mode`;
      theme.setAttribute("aria-label", theme.title);
    };
    label();
    theme.hidden = false;
    preference.addEventListener("change", label);
    theme.addEventListener("click", () => {
      root.dataset.theme = dark() ? "light" : "dark";
      try { localStorage.setItem("grugdb-theme", root.dataset.theme); } catch {}
      label();
    });

    const tooltip = document.createElement("div");
    tooltip.id = "api-tooltip";
    tooltip.className = "api-tooltip";
    tooltip.setAttribute("role", "dialog");
    tooltip.setAttribute("aria-labelledby", "api-tooltip-title");
    tooltip.hidden = true;
    const header = document.createElement("div");
    header.className = "api-tooltip-header";
    const name = document.createElement("strong");
    name.id = "api-tooltip-title";
    const close = document.createElement("button");
    close.type = "button";
    close.textContent = "×";
    close.setAttribute("aria-label", "Close preview");
    header.append(name, close);
    const controls = document.createElement("div");
    controls.className = "api-tooltip-controls";
    const tablist = document.createElement("div");
    tablist.setAttribute("role", "tablist");
    tablist.setAttribute("aria-label", "Preview view");
    const tabs = ["docs", "source"].map((view) => {
      const tab = document.createElement("button");
      tab.type = "button";
      tab.id = `api-tooltip-tab-${view}`;
      tab.dataset.view = view;
      tab.textContent = view === "source" ? "Source" : "Docs";
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-controls", `api-tooltip-${view}`);
      tablist.append(tab);
      return tab;
    });
    const reference = document.createElement("a");
    reference.textContent = "Reference ↗";
    controls.append(tablist, reference);
    const body = document.createElement("div");
    body.className = "api-tooltip-body";
    tooltip.append(header, controls, body);
    document.body.append(tooltip);
    let active = null;
    let focusVersion = 0;
    let hideTimer = null;
    let restoringFocus = false;
    const cancelHide = () => {
      clearTimeout(hideTimer);
      hideTimer = null;
    };
    const hide = () => {
      cancelHide();
      if (active) {
        active.setAttribute("aria-expanded", "false");
        active.removeAttribute("aria-controls");
      }
      active = null;
      tooltip.hidden = true;
    };
    const dismiss = () => { focusVersion++; hide(); };
    const scheduleHide = () => {
      cancelHide();
      hideTimer = setTimeout(() => {
        if (active && !active.matches(":hover") && !tooltip.matches(":hover")
          && document.activeElement !== active && !tooltip.contains(document.activeElement)) dismiss();
      }, 180);
    };
    const position = () => {
      if (!active) return;
      const bounds = active.getBoundingClientRect();
      const width = document.documentElement.clientWidth;
      const height = window.innerHeight;
      tooltip.style.maxHeight = `${Math.max(0, height - 16)}px`;
      const box = tooltip.getBoundingClientRect();
      const below = Math.max(0, height - bounds.bottom - 16);
      const above = Math.max(0, bounds.top - 16);
      const placeBelow = box.height <= below || below >= above;
      tooltip.style.maxHeight = `${placeBelow ? below : above}px`;
      const fitted = tooltip.getBoundingClientRect();
      const left = Math.max(8, Math.min(bounds.left, width - fitted.width - 8));
      const top = placeBelow ? bounds.bottom + 8 : bounds.top - fitted.height - 8;
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${Math.max(8, Math.min(top, height - fitted.height - 8))}px`;
    };
    const selectView = (view) => {
      tabs.forEach((tab) => {
        const selected = tab.dataset.view === view;
        tab.setAttribute("aria-selected", String(selected));
        tab.tabIndex = selected ? 0 : -1;
      });
      body.querySelectorAll("[data-view]").forEach((panel) => {
        panel.hidden = panel.dataset.view !== view;
      });
      tooltip.dataset.view = view;
      position();
    };
    const show = (link) => {
      cancelHide();
      if (active === link) return;
      const template = document.getElementById(`api-preview-${link.dataset.term}`);
      if (!(template instanceof HTMLTemplateElement)) return;
      hide();
      active = link;
      name.textContent = link.dataset.term;
      reference.href = link.href;
      body.replaceChildren(template.content.cloneNode(true));
      body.querySelectorAll("[data-view]").forEach((panel) => {
        panel.id = `api-tooltip-${panel.dataset.view}`;
        panel.setAttribute("role", "tabpanel");
        panel.setAttribute("aria-labelledby", `api-tooltip-tab-${panel.dataset.view}`);
        panel.tabIndex = 0;
      });
      tooltip.hidden = false;
      link.setAttribute("aria-controls", tooltip.id);
      link.setAttribute("aria-expanded", "true");
      selectView("docs");
    };
    const closePreview = () => {
      const trigger = active;
      const returnFocus = tooltip.contains(document.activeElement);
      dismiss();
      if (returnFocus && trigger) {
        restoringFocus = true;
        trigger.focus({ preventScroll: true });
        restoringFocus = false;
      }
    };
    tabs.forEach((tab, index) => {
      tab.addEventListener("click", () => selectView(tab.dataset.view));
      tab.addEventListener("keydown", (event) => {
        let next;
        if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
        else if (event.key === "ArrowLeft") next = (index + tabs.length - 1) % tabs.length;
        else if (event.key === "Home") next = 0;
        else if (event.key === "End") next = tabs.length - 1;
        else return;
        event.preventDefault();
        selectView(tabs[next].dataset.view);
        tabs[next].focus({ preventScroll: true });
      });
    });
    close.addEventListener("click", closePreview);
    tooltip.addEventListener("mouseenter", cancelHide);
    tooltip.addEventListener("mouseleave", scheduleHide);
    tooltip.addEventListener("focusin", cancelHide);
    tooltip.addEventListener("focusout", scheduleHide);
    document.querySelectorAll("a.api-term").forEach((link) => {
      if (!document.getElementById(`api-preview-${link.dataset.term}`)) return;
      link.removeAttribute("title");
      link.setAttribute("aria-haspopup", "dialog");
      link.setAttribute("aria-expanded", "false");
      link.addEventListener("mouseenter", () => {
        focusVersion++;
        if (!tooltip.contains(document.activeElement)) show(link);
      });
      link.addEventListener("mouseleave", scheduleHide);
      link.addEventListener("focus", () => {
        const version = ++focusVersion;
        if (restoringFocus) return;
        // Keyboard focus may scroll the link into view before the next frame.
        requestAnimationFrame(() => {
          if (version === focusVersion && document.activeElement === link) show(link);
        });
      });
      link.addEventListener("blur", () => { focusVersion++; scheduleHide(); });
      link.addEventListener("keydown", (event) => {
        if (event.key !== "ArrowDown") return;
        event.preventDefault();
        focusVersion++;
        show(link);
        tabs.find((tab) => tab.getAttribute("aria-selected") === "true").focus({ preventScroll: true });
      });
      link.addEventListener("click", dismiss);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && active) {
        event.preventDefault();
        closePreview();
      }
    });
    document.addEventListener("scroll", (event) => {
      // Preserve pending focus frames when the browser scrolls a trigger into view.
      if (!tooltip.contains(event.target)) hide();
    }, true);
    window.addEventListener("blur", dismiss);
    window.addEventListener("resize", dismiss);
    window.addEventListener("beforeprint", dismiss);
  });
})();
