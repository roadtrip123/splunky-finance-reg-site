/* Fills every [data-lab-details] block from /api/credentials.
   The values are never in the page source: an unregistered visitor gets a 401 here and sees a
   prompt to register, and the LiteLLM key reaches the browser only behind the cookie. */
(function () {
  "use strict";

  var POLL_MS = 3000;
  var slots = document.querySelectorAll("[data-lab-details]");

  function escape(text) {
    return String(text == null ? "" : text).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function row(label, value, options) {
    options = options || {};
    if (!value) return "";
    var shown = options.secret ? "•".repeat(12) : escape(value);
    var klass = options.link ? "" : "value";
    var inner = options.link
      ? '<a href="' + escape(value) + '" target="_blank" rel="noopener">' + escape(value) + "</a>"
      : '<span class="' + klass + '" data-text="' + escape(value) + '">' + shown + "</span>";
    var buttons = '<button class="copy" data-copy="' + escape(value) + '">copy</button>';
    if (options.secret) buttons = '<button class="copy" data-reveal>show</button>' + buttons;
    return '<div class="detail"><span>' + escape(label) + "</span><span>" + inner +
      buttons + "</span></div>";
  }

  function render(data, opts) {
    opts = opts || {};
    var parts = ['<section class="card details"><p class="eyebrow cyan">' +
      '<span class="live-dot"></span>Checked in</p><h2>Your lab details</h2>'];

    parts.push("<h3>Your bank</h3>");
    if (data.instance.url) {
      parts.push(row("App", data.instance.url, { link: true }));
      parts.push(row("Presenter portal", data.instance.url.replace(/\/+$/, "") + "/demo-admin",
        { link: true }));
    } else {
      parts.push('<div class="detail"><span>App</span><span class="pending">' +
        "waiting for your instructor to add instances</span></div>");
    }
    parts.push(row("Customer login", data.instance.account));
    parts.push(row("Customer password", data.instance.password));
    parts.push(row("Presenter password", data.instance.presenter_password));

    parts.push("<h3>Galileo</h3>");
    if (data.galileo.ready && data.galileo.existing) {
      parts.push(row("Your account", data.galileo.email));
      parts.push('<div class="detail"><span>Password</span><span>You already have a Galileo ' +
        "account, so sign in with the password you normally use. Forgotten it? Use " +
        "<strong>Forgot password</strong> on the console sign-in page.</span></div>");
    } else if (data.galileo.ready) {
      parts.push(row("Your account", data.galileo.email));
      parts.push(row("Password", data.galileo.password, { secret: true }));
    } else {
      var ahead = data.galileo.queue_ahead || 0;
      var wait = ahead > 1
        ? "creating your Galileo account, " + ahead + " ahead of you, about " +
          Math.max(1, Math.round(data.galileo.queue_seconds / 15) * 15) + " seconds"
        : "creating your Galileo account";
      parts.push('<div class="detail"><span>Your account</span><span class="pending">' +
        escape(wait) + "</span></div>");
    }
    parts.push(row("Console URL", data.galileo.console_url, { link: true }));
    parts.push(row("API URL", data.galileo.api_url));
    parts.push(row("Agent Control URL", data.galileo.agent_control_url));

    parts.push("<h3>Model endpoint</h3>");
    parts.push(row("Provider", "Custom (OpenAI-compatible)"));
    parts.push(row("Base URL", data.llm.base_url));
    parts.push(row("Model", data.llm.model));
    parts.push(row("API key", data.llm.api_key, { secret: true }));
    if (data.llm.integration_json) {
      parts.push('<details class="snippet"' + (opts.openSnippet ? " open" : "") + ">" +
        "<summary>Galileo custom integration, filled in</summary>" +
        '<p class="snippet-help">Step 4: paste this into the custom integration in Galileo. It ' +
        "already has your gateway, model and key.</p>" +
        '<div class="snippet-bar"><button class="copy wide-copy" data-copy="' +
        escape(data.llm.integration_json) + '">Copy JSON</button></div>' +
        "<pre>" + escape(data.llm.integration_json) + "</pre></details>");
    }

    parts.push("</section>");
    return parts.join("");
  }

  function prompt() {
    return '<section class="card details"><p class="eyebrow cyan">Your lab details</p>' +
      "<h2>Check in to see them.</h2>" +
      '<p class="checkin-text">Your instance, your Galileo account and the model endpoint appear ' +
      "here once you have checked in, and stay one click away on every page.</p>" +
      '<a class="button" href="/#check-in">Check in</a></section>';
  }

  function paint(html) {
    slots.forEach(function (slot) { slot.innerHTML = html; });
  }

  /* My lab shows the integration JSON open; the drawer and the briefing keep it folded. */
  function paintDetails(data) {
    slots.forEach(function (slot) {
      slot.innerHTML = render(data, { openSnippet: slot.hasAttribute("data-open-snippet") });
    });
    paintSnippets(data);
  }

  /* The integration body in the Step 4 guide: the participant's own, the same as on My lab. */
  var snippets = document.querySelectorAll("[data-integration-snippet]");
  function paintSnippets(data) {
    snippets.forEach(function (slot) {
      if (!data || !data.llm || !data.llm.integration_json) {
        slot.innerHTML = '<div class="snippet-locked"><p>Check in and this fills in with your ' +
          "gateway, model and key, ready to paste.</p>" +
          '<a class="button" href="/#check-in">Check in</a></div>';
        return;
      }
      slot.innerHTML = '<div class="snippet-bar"><button class="copy wide-copy" data-copy="' +
        escape(data.llm.integration_json) + '">Copy JSON</button></div>' +
        "<pre>" + escape(data.llm.integration_json) + "</pre>";
    });
  }

  function wire() {
    document.addEventListener("click", function (event) {
      var reveal = event.target.closest("[data-reveal]");
      if (reveal) {
        var span = reveal.parentNode.querySelector(".value");
        var hidden = span.textContent.indexOf("•") === 0;
        span.textContent = hidden ? span.getAttribute("data-text") : "•".repeat(12);
        reveal.textContent = hidden ? "hide" : "show";
        return;
      }
      var copy = event.target.closest("[data-copy]");
      if (!copy) return;
      var text = copy.getAttribute("data-copy");
      var done = function () {
        var was = copy.textContent;
        copy.textContent = "copied";
        setTimeout(function () { copy.textContent = was; }, 1200);
      };
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, done);
      else done();
    });
  }

  function load() {
    fetch("/api/credentials", { credentials: "same-origin" })
      .then(function (response) {
        if (response.status === 401) { paint(prompt()); paintSnippets(null); return null; }
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (data) {
        if (!data) return;
        paintDetails(data);
        /* Keep polling only while something is still being provisioned. */
        if (!data.galileo.ready || !data.instance.url) setTimeout(load, POLL_MS);
      })
      .catch(function () { setTimeout(load, POLL_MS * 2); });
  }

  wire();
  if (slots.length) load();

  /* Show or hide a password field, for the passphrase on the admin page. */
  document.addEventListener("click", function (event) {
    var toggle = event.target.closest("[data-reveal-toggle]");
    if (!toggle) return;
    var input = toggle.parentNode.querySelector("[data-reveal-input]");
    if (!input) return;
    var hidden = input.type === "password";
    input.type = hidden ? "text" : "password";
    toggle.textContent = hidden ? "Hide" : "Show";
  });

  /* "Mark step done" under the steps the tracker cannot see on the participant's instance. */
  document.addEventListener("click", function (event) {
    var toggle = event.target.closest("[data-step-toggle]");
    if (!toggle) return;
    var box = toggle.closest("[data-step]");
    var step = parseInt(box.getAttribute("data-step"), 10);
    var done = !box.classList.contains("is-done");
    fetch("/api/progress", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ step: step, done: done })
    }).then(function (response) {
      if (!response.ok) return;
      box.classList.toggle("is-done", done);
      box.querySelector("button[data-step-toggle]:not(.link)").innerHTML =
        done ? "&#10003; Step " + step + " done" : "Mark step " + step + " done";
      box.querySelector(".step-done-note").innerHTML = done
        ? '<button type="button" class="link" data-step-toggle>undo</button>'
        : "So your instructor can see where you are.";
    });
  });

  /* The admin progress board refreshes itself. */
  var board = document.querySelector("[data-progress]");
  if (board) {
    setInterval(function () {
      if (document.hidden) return;
      fetch("/admin/progress", { credentials: "same-origin" })
        .then(function (response) { return response.ok ? response.text() : null; })
        .then(function (html) {
          if (!html) return;
          var current = document.querySelector("[data-progress]");
          if (current) current.outerHTML = html;
        })
        .catch(function () {});
    }, 15000);
  }

  /* The lab-details drawer, opened from the dock at the bottom right of every page. */
  var drawer = document.querySelector("[data-drawer]");
  function openDrawer() {
    if (!drawer) return;
    drawer.hidden = false;
    document.body.style.overflow = "hidden";
    var close = drawer.querySelector("[data-drawer-close]");
    if (close) close.focus();
  }
  function closeDrawer() {
    if (!drawer || drawer.hidden) return;
    drawer.hidden = true;
    document.body.style.overflow = "";
    var opener = document.querySelector("[data-drawer-open]");
    if (opener) opener.focus();
  }
  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-drawer-open]")) { openDrawer(); return; }
    if (event.target.closest("[data-drawer-close]") || event.target === drawer) closeDrawer();
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeDrawer();
  });

  /* Highlight the section the reader is in. */
  var links = document.querySelectorAll(".toc a");
  if (links.length && "IntersectionObserver" in window) {
    var byId = {};
    links.forEach(function (link) { byId[link.getAttribute("href").slice(1)] = link; });
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        var link = byId[entry.target.id];
        if (!link) return;
        if (entry.isIntersecting) {
          links.forEach(function (other) { other.classList.remove("active"); });
          link.classList.add("active");
        }
      });
    }, { rootMargin: "-80px 0px -70% 0px" });
    Object.keys(byId).forEach(function (id) {
      var heading = document.getElementById(id);
      if (heading) observer.observe(heading);
    });
  }
})();

/* The drifting network behind every page: nodes in the four stripe colours, joined when close.
   Static for anyone who asks for reduced motion, and paused while the tab is hidden. */
(function () {
  "use strict";
  var canvas = document.querySelector("canvas.net");
  if (!canvas || !canvas.getContext) return;
  var ctx = canvas.getContext("2d");
  var colours = ["#02C8FF", "#0A60FF", "#FF007F", "#FF9000"];
  var still = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var nodes = [], width = 0, height = 0, ratio = 1, running = true, LINK = 170;

  function size() {
    ratio = Math.min(window.devicePixelRatio || 1, 2);
    width = window.innerWidth; height = window.innerHeight;
    canvas.width = width * ratio; canvas.height = height * ratio;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    var count = Math.round(Math.min(64, Math.max(22, width * height / 24000)));
    nodes = [];
    for (var i = 0; i < count; i++) {
      nodes.push({
        x: Math.random() * width, y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.16, vy: (Math.random() - 0.5) * 0.16,
        r: 1.6 + Math.random() * 2.2, c: colours[i % 4], ring: Math.random() < 0.4
      });
    }
  }

  function draw() {
    ctx.clearRect(0, 0, width, height);
    for (var i = 0; i < nodes.length; i++) {
      for (var j = i + 1; j < nodes.length; j++) {
        var dx = nodes[i].x - nodes[j].x, dy = nodes[i].y - nodes[j].y;
        var d = Math.sqrt(dx * dx + dy * dy);
        if (d < LINK) {
          ctx.globalAlpha = (1 - d / LINK) * 0.22;
          ctx.strokeStyle = nodes[i].c;
          ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(nodes[i].x, nodes[i].y); ctx.lineTo(nodes[j].x, nodes[j].y);
          ctx.stroke();
        }
      }
    }
    for (var k = 0; k < nodes.length; k++) {
      var n = nodes[k];
      ctx.globalAlpha = 0.5; ctx.fillStyle = n.c;
      ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2); ctx.fill();
      if (n.ring) {
        ctx.globalAlpha = 0.28; ctx.strokeStyle = n.c; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r + 7, 0, Math.PI * 2); ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
  }

  function step() {
    if (!running) return;
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      n.x += n.vx; n.y += n.vy;
      if (n.x < -20) n.x = width + 20; else if (n.x > width + 20) n.x = -20;
      if (n.y < -20) n.y = height + 20; else if (n.y > height + 20) n.y = -20;
    }
    draw();
    window.requestAnimationFrame(step);
  }

  size();
  window.addEventListener("resize", function () { size(); if (still) draw(); });
  if (still) { draw(); return; }
  document.addEventListener("visibilitychange", function () {
    running = !document.hidden;
    if (running) window.requestAnimationFrame(step);
  });
  window.requestAnimationFrame(step);
})();
