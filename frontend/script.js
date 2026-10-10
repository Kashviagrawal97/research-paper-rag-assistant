(() => {
    const $ = (sel) => document.querySelector(sel);
    const BUSY = new Set(["fetching", "reading", "embedding"]);
    const MAX_FILES = 8;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  
    const el = {
      tabTopic: $("#tab-topic"), tabUpload: $("#tab-upload"),
      panelTopic: $("#panel-topic"), panelUpload: $("#panel-upload"),
      topicInput: $("#topic-input"), topicSubmit: $("#topic-submit"),
      dropzone: $("#dropzone"), fileInput: $("#file-input"), fileList: $("#file-list"),
      uploadError: $("#upload-error"), uploadSubmit: $("#upload-submit"),
      progress: $("#progress"), stages: $("#stages"), bar: $("#bar"), barFill: $("#bar-fill"),
      progressMessage: $("#progress-message"), progressNote: $("#progress-note"),
      papers: $("#papers"), paperList: $("#paper-list"),
      empty: $("#empty"), emptyText: $("#empty-text"), starters: $("#starters"),
      thread: $("#thread"), askForm: $("#ask-form"), question: $("#question"), askSubmit: $("#ask-submit"),
    };
  
    let mode = "topic";        // which tab is open
    let buildMode = "topic";   // which tab started the current build
    let files = [];
    let pollTimer = null;
    let ready = false;
    let building = false;
    let answering = false;
  
    /* ---------------- Tabs ---------------- */
    function setMode(next) {
      mode = next;
      const isTopic = next === "topic";
      el.tabTopic.setAttribute("aria-selected", String(isTopic));
      el.tabUpload.setAttribute("aria-selected", String(!isTopic));
      el.tabTopic.tabIndex = isTopic ? 0 : -1;
      el.tabUpload.tabIndex = isTopic ? -1 : 0;
      el.panelTopic.hidden = !isTopic;
      el.panelUpload.hidden = isTopic;
    }
    el.tabTopic.addEventListener("click", () => setMode("topic"));
    el.tabUpload.addEventListener("click", () => setMode("upload"));
    [el.tabTopic, el.tabUpload].forEach((tab) =>
      tab.addEventListener("keydown", (e) => {
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
          const next = mode === "topic" ? "upload" : "topic";
          setMode(next);
          (next === "topic" ? el.tabTopic : el.tabUpload).focus();
        }
      })
    );
  
    /* ---------------- Upload ---------------- */
    const fmtSize = (b) => (b >= 1048576 ? (b / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB");
  
    function showUploadError(msg) {
      el.uploadError.textContent = msg || "";
      el.uploadError.hidden = !msg;
    }
  
    function addFiles(list) {
      showUploadError("");
      for (const f of list) {
        if (!f.name.toLowerCase().endsWith(".pdf")) {
          showUploadError(`\u201c${f.name}\u201d is not a PDF, so it was skipped.`);
          continue;
        }
        if (files.some((x) => x.name === f.name && x.size === f.size)) continue;
        if (files.length >= MAX_FILES) {
          showUploadError(`You can add up to ${MAX_FILES} PDFs.`);
          break;
        }
        files.push(f);
      }
      renderFiles();
    }
  
    function renderFiles() {
      el.fileList.textContent = "";
      files.forEach((f, i) => {
        const li = document.createElement("li");
        const name = document.createElement("span");
        name.className = "name"; name.textContent = f.name; name.title = f.name;
        const size = document.createElement("span");
        size.className = "size"; size.textContent = fmtSize(f.size);
        const rm = document.createElement("button");
        rm.type = "button"; rm.className = "remove"; rm.textContent = "Remove";
        rm.setAttribute("aria-label", `Remove ${f.name}`);
        rm.addEventListener("click", () => { files.splice(i, 1); showUploadError(""); renderFiles(); });
        li.append(name, size, rm);
        el.fileList.append(li);
      });
      updateBuildButtons();
    }
  
    el.fileInput.addEventListener("change", () => { addFiles(Array.from(el.fileInput.files)); el.fileInput.value = ""; });
    ["dragenter", "dragover"].forEach((t) =>
      el.dropzone.addEventListener(t, (e) => { e.preventDefault(); el.dropzone.classList.add("drag"); })
    );
    ["dragleave", "drop"].forEach((t) =>
      el.dropzone.addEventListener(t, (e) => { e.preventDefault(); el.dropzone.classList.remove("drag"); })
    );
    el.dropzone.addEventListener("drop", (e) => addFiles(Array.from(e.dataTransfer.files)));
  
    /* ---------------- Build library ---------------- */
    function updateBuildButtons() {
      el.topicSubmit.disabled = building;
      el.uploadSubmit.disabled = building || files.length === 0;
    }
  
    function updateAsk() {
      const on = ready && !building && !answering;
      el.question.disabled = !on;
      el.askSubmit.disabled = !on;
      el.question.placeholder = ready ? "Ask something about your papers" : "Build a library to start asking";
    }
  
    function clearThread() {
      el.thread.textContent = "";
      el.empty.hidden = false;
    }
  
    async function startBuild(request) {
      clearThread();
      ready = false;
      building = true;
      buildMode = mode;
      el.papers.hidden = true;
      showProgress({ stage: mode === "topic" ? "fetching" : "reading", message: "Starting", percent: 0 });
      updateBuildButtons();
      updateAsk();
      setEmptyForWaiting();
  
      try {
        const res = await request();
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || "Could not start building the library.");
        startPolling();
      } catch (err) {
        building = false;
        showError(err.message);
        updateBuildButtons();
      }
    }
  
    el.panelTopic.addEventListener("submit", (e) => {
      e.preventDefault();
      const topic = el.topicInput.value.trim();
      if (!topic) { el.topicInput.focus(); return; }
      startBuild(() => fetch("/api/build-from-topic", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic }),
      }));
    });
  
    el.panelUpload.addEventListener("submit", (e) => {
      e.preventDefault();
      if (!files.length) return;
      const body = new FormData();
      files.forEach((f) => body.append("files", f));
      startBuild(() => fetch("/api/build-from-upload", { method: "POST", body }));
    });
  
    /* ---------------- Progress ---------------- */
    const ORDER = ["fetching", "reading", "embedding"];
  
    function showProgress(s) {
      el.progress.hidden = false;
      el.progressMessage.classList.remove("error");
      el.stages.hidden = false;
      el.stages.querySelector('[data-stage="fetching"]').classList.toggle("hidden", buildMode !== "topic");
  
      const current = s.stage === "ready" ? ORDER.length : ORDER.indexOf(s.stage);
      el.stages.querySelectorAll("li").forEach((li) => {
        const idx = ORDER.indexOf(li.dataset.stage);
        li.classList.toggle("done", idx < current);
        li.classList.toggle("active", idx === current);
        if (idx === current) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
      });
  
      const embedding = s.stage === "embedding";
      el.bar.hidden = !embedding;
      el.barFill.style.width = (s.percent || 0) + "%";
      el.progressNote.hidden = !(embedding || s.stage === "reading");
      el.progressMessage.textContent = s.message || "";
    }
  
    function showError(message) {
      el.progress.hidden = false;
      el.stages.hidden = true;
      el.bar.hidden = true;
      el.progressNote.hidden = true;
      el.progressMessage.classList.add("error");
      el.progressMessage.textContent = message;
      el.progressMessage.setAttribute("role", "alert");
    }
  
    function startPolling() {
      stopPolling();
      pollTimer = setInterval(fetchStatus, 1500);
    }
    function stopPolling() {
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    }
  
    async function fetchStatus() {
      try {
        const res = await fetch("/api/status");
        applyStatus(await res.json());
      } catch {
        /* server briefly unreachable: keep polling */
      }
    }
  
    function applyStatus(s) {
      if (BUSY.has(s.stage)) {
        building = true;
        showProgress(s);
      } else if (s.stage === "ready") {
        stopPolling();
        if (building) showProgress(s);   // skip the progress panel when reopening an existing library
        building = false;
        ready = true;
        renderPapers(s.papers || []);
        setEmptyForReady();
      } else if (s.stage === "error") {
        stopPolling();
        building = false;
        ready = false;
        showError(s.message);
      }
      updateBuildButtons();
      updateAsk();
    }
  
    function renderPapers(list) {
      el.paperList.textContent = "";
      list.forEach((name) => {
        const li = document.createElement("li");
        li.textContent = name.replace(/\.pdf$/i, "");
        li.title = name;
        el.paperList.append(li);
      });
      el.papers.hidden = list.length === 0;
    }
  
    /* ---------------- Empty state & starters ---------------- */
    const STARTERS = [
      "What is the main contribution of each paper?",
      "What methods do these papers use?",
      "What limitations do the authors mention?",
    ];
  
    function setEmptyForWaiting() {
      el.emptyText.textContent = "Building your library. You can ask questions as soon as it is ready.";
      el.starters.hidden = true;
    }
  
    function setEmptyForReady() {
      if (el.thread.children.length) return;
      el.empty.hidden = false;
      el.emptyText.textContent = "Your library is ready. Ask anything about these papers, or start with one of these.";
      el.starters.textContent = "";
      STARTERS.forEach((q) => {
        const b = document.createElement("button");
        b.type = "button"; b.className = "starter"; b.textContent = q;
        b.addEventListener("click", () => ask(q));
        el.starters.append(b);
      });
      el.starters.hidden = false;
    }
  
    /* ---------------- Asking ---------------- */
    const escapeHtml = (s) =>
      s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const inline = (s) =>
      escapeHtml(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
  
    function renderAnswer(text) {
      return text.trim().split(/\n{2,}/).map((block) => {
        const lines = block.split("\n");
        if (lines.every((l) => /^\s*[-*]\s+/.test(l))) {
          return "<ul>" + lines.map((l) => "<li>" + inline(l.replace(/^\s*[-*]\s+/, "")) + "</li>").join("") + "</ul>";
        }
        return "<p>" + lines.map(inline).join("<br>") + "</p>";
      }).join("");
    }
  
    function renderSources(entry, sources) {
      if (!sources.length) return;
      const wrap = document.createElement("div");
      wrap.className = "sources";
      const h = document.createElement("h4");
      h.textContent = "Where this came from";
      const ul = document.createElement("ul");
  
      sources.forEach((s) => {
        const li = document.createElement("li");
        const name = document.createElement("span");
        name.className = "src-name"; name.textContent = s.file.replace(/\.pdf$/i, "");
        li.append(name);
        if (s.page) {
          const page = document.createElement("span");
          page.className = "src-page"; page.textContent = "page " + s.page;
          li.append(page);
        }
        if (s.snippet) {
          const d = document.createElement("details");
          const sm = document.createElement("summary"); sm.textContent = "Show passage";
          const p = document.createElement("p"); p.textContent = s.snippet + "\u2026";
          d.append(sm, p);
          li.append(d);
        }
        ul.append(li);
      });
      wrap.append(h, ul);
      entry.append(wrap);
    }
  
    async function ask(question) {
      question = question.trim();
      if (!question || !ready || building || answering) return;
  
      answering = true;
      updateAsk();
      el.empty.hidden = true;
  
      const entry = document.createElement("article");
      entry.className = "entry";
      const h = document.createElement("h3"); h.textContent = question;
      const body = document.createElement("div");
      body.className = "answer pending"; body.textContent = "Reading the papers\u2026";
      entry.append(h, body);
      el.thread.append(entry);
      entry.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
      el.question.value = "";
  
      try {
        const res = await fetch("/api/ask", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || "Could not get an answer.");
        body.classList.remove("pending");
        body.innerHTML = renderAnswer(data.answer || "");
        renderSources(entry, data.sources || []);
      } catch (err) {
        body.classList.remove("pending");
        body.classList.add("error");
        body.textContent = err.message;
      } finally {
        answering = false;
        updateAsk();
        el.question.focus();
      }
    }
  
    el.askForm.addEventListener("submit", (e) => { e.preventDefault(); ask(el.question.value); });
    el.question.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(el.question.value); }
    });
  
    /* ---------------- Init ---------------- */
    setMode("topic");
    updateBuildButtons();
    updateAsk();
    fetchStatus().then(() => {
      // Resume if a build is already running (e.g. after a page refresh)
      if (building) startPolling();
    });
  })();