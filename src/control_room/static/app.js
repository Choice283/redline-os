// Redline OS Control Room V0 — Projects screen.
// Read-only: fetches /api/projects and renders whatever the server
// returns, including degraded/unknown states. No writes, ever.

function pillClass(value) {
  return String(value || "unknown").toLowerCase().replace(/_/g, "-");
}

function renderGitStatus(git) {
  const branch = git.detached_head ? "DETACHED HEAD" : (git.branch || "UNKNOWN");
  const head = git.head_sha_short || "UNKNOWN";
  const tracking = git.tracking || "UNKNOWN";
  let trackingLabel = tracking;
  if (tracking === "AHEAD" && git.ahead != null) trackingLabel = `AHEAD (${git.ahead})`;
  if (tracking === "BEHIND" && git.behind != null) trackingLabel = `BEHIND (${git.behind})`;
  if (tracking === "DIVERGED" && git.ahead != null && git.behind != null) {
    trackingLabel = `DIVERGED (+${git.ahead}/-${git.behind})`;
  }

  const pills = [
    `<span class="pill">${escapeHtml(branch)}</span>`,
    `<span class="pill ${pillClass(git.working_tree)}">${escapeHtml(git.working_tree || "UNKNOWN")}</span>`,
    `<span class="pill ${pillClass(tracking)}">${escapeHtml(trackingLabel)}</span>`,
    `<span class="pill">${escapeHtml(head)}</span>`,
  ];

  let html = `<div class="git-status">${pills.join("")}</div>`;
  if (git.error) {
    html += `<p class="error-text">Git error: ${escapeHtml(git.error)}</p>`;
  }
  return html;
}

function renderState(state, stateError) {
  if (!state) {
    return `<p class="error-text">Project state unavailable: ${escapeHtml(stateError || "unknown")}</p>`;
  }

  const validationClass = `validation-${pillClass(state.validation.status).replace(/-/g, "_")}`;

  return `
    <dl>
      <dt>Current mission</dt>
      <dd>${escapeHtml(state.current_mission.title)} (${escapeHtml(state.current_mission.phase)})</dd>

      <dt>Latest checkpoint</dt>
      <dd>${escapeHtml(state.latest_checkpoint.label)} — <code>${escapeHtml(state.latest_checkpoint.commit)}</code></dd>

      <dt>Validation</dt>
      <dd class="validation-line ${validationClass}">${escapeHtml(state.validation.status.toUpperCase())} — ${escapeHtml(state.validation.summary.trim())}</dd>
    </dl>
  `;
}

function renderProject(snapshot) {
  const attention = snapshot.attention || { required: true, reason: "attention state unavailable" };
  const bannerClass = attention.required ? "required" : "ok";
  const bannerText = attention.required
    ? `ACTION REQUIRED — ${attention.reason || "see below"}`
    : "NO ACTION REQUIRED";

  return `
    <section class="card">
      <h2>${escapeHtml(snapshot.name)}</h2>
      <p class="summary">${escapeHtml(snapshot.state ? snapshot.state.summary.trim() : "Project state unavailable.")}</p>
      <div class="attention-banner ${bannerClass}">${escapeHtml(bannerText)}</div>
      ${renderGitStatus(snapshot.git)}
      ${renderState(snapshot.state, snapshot.state_error)}
    </section>
  `;
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = String(value);
  return div.innerHTML;
}

async function loadProjects() {
  const root = document.getElementById("projects");
  try {
    const response = await fetch("/api/projects");
    if (!response.ok) {
      throw new Error(`request failed: ${response.status} ${response.statusText}`);
    }
    const snapshots = await response.json();
    if (!Array.isArray(snapshots) || snapshots.length === 0) {
      root.innerHTML = '<p class="fatal-error">No projects registered.</p>';
      return;
    }
    root.innerHTML = snapshots.map(renderProject).join("");
  } catch (err) {
    root.innerHTML = `<p class="fatal-error">Failed to load projects: ${escapeHtml(err.message)}</p>`;
  }
}

loadProjects();
