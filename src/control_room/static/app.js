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
    <a class="card" href="#/projects/${encodeURIComponent(snapshot.project_id)}">
      <h2>${escapeHtml(snapshot.name)}</h2>
      <p class="summary">${escapeHtml(snapshot.state ? snapshot.state.summary.trim() : "Project state unavailable.")}</p>
      <div class="attention-banner ${bannerClass}">${escapeHtml(bannerText)}</div>
      ${renderGitStatus(snapshot.git)}
      ${renderState(snapshot.state, snapshot.state_error)}
    </a>
  `;
}

const BACK_LINK = '<a href="#/" class="back-link">&larr; Back to Projects</a>';

// Mission & Checkpoint History -- read-only, derived fresh on every
// request from docs/control_room/*_CLOSURE_*.md via the same
// GET /api/projects/{project_id} response the rest of the Detail screen
// uses. Renders whatever the API returns, including parse_error and
// unresolved checkpoints, rather than assuming every historical record
// is complete.
function renderHistoryEntry(entry) {
  const statusClass = entry.status === "closed" ? "clean" : "error";
  const label = entry.mission_number != null ? `Mission ${entry.mission_number}` : "Mission (unknown)";
  const heading = entry.title ? `${label} — ${entry.title}` : label;

  const checkpoint = entry.checkpoint_commit || "UNKNOWN";
  let checkpointNote = "";
  if (entry.checkpoint_commit && entry.checkpoint_resolved === false) {
    checkpointNote = ' <span class="error-text">(does not resolve in repository)</span>';
  } else if (entry.checkpoint_commit && entry.checkpoint_resolved == null) {
    checkpointNote = ' <span class="error-text">(resolution unknown)</span>';
  }

  const parseError = entry.parse_error
    ? `<p class="error-text">${escapeHtml(entry.parse_error)}</p>`
    : "";

  return `
    <li class="history-entry">
      <div class="history-header">
        <span class="pill ${statusClass}">${escapeHtml((entry.status || "unknown").toUpperCase())}</span>
        <strong>${escapeHtml(heading)}</strong>
      </div>
      <dl>
        <dt>Checkpoint</dt>
        <dd><code>${escapeHtml(checkpoint)}</code>${checkpointNote}</dd>

        <dt>Closure document</dt>
        <dd><code>${escapeHtml(entry.closure_document)}</code></dd>

        <dt>Closure date</dt>
        <dd>${escapeHtml(entry.closure_date || "UNKNOWN")}</dd>
      </dl>
      ${parseError}
      ${renderMissionScopeOutcome(entry)}
      ${renderValidationEvidence(entry)}
      ${renderCheckpointChangeSet(entry)}
    </li>
  `;
}

// Validation & Evidence Detail (Mission 5) -- a read-only drill-down
// reachable from each Mission & Checkpoint History entry. Renders the
// verbatim text of the closure document's own Validation/Independent
// Review/CI sections (whichever are present); a missing section is shown
// as an explicit message, never invented or left blank without
// explanation. No new route: this data already rides on the same
// GET /api/projects/{project_id} response as the rest of the history
// entry.
function renderEvidenceSection(label, text) {
  if (!text) {
    return `
      <div class="evidence-section">
        <h4>${escapeHtml(label)}</h4>
        <p class="error-text">No ${escapeHtml(label.toLowerCase())} section recorded in this closure document.</p>
      </div>
    `;
  }
  return `
    <div class="evidence-section">
      <h4>${escapeHtml(label)}</h4>
      <pre class="evidence-text">${escapeHtml(text)}</pre>
    </div>
  `;
}

function renderValidationEvidence(entry) {
  return `
    <details class="evidence-details">
      <summary>Validation &amp; Evidence Detail</summary>
      ${renderEvidenceSection("Validation", entry.validation_section)}
      ${renderEvidenceSection("Independent Review", entry.independent_review_section)}
      ${renderEvidenceSection("CI", entry.ci_section)}
    </details>
  `;
}

// Mission Scope & Outcome Detail (Mission 6) -- a second read-only
// drill-down per history entry, alongside Validation & Evidence Detail.
// Renders the verbatim Purpose/Delivered Capability/Deferred Work text
// from the closure document; a missing section is shown as an explicit
// message, never invented. Same data source, same GET
// /api/projects/{project_id} response, no new route.
function renderMissionScopeOutcome(entry) {
  return `
    <details class="evidence-details">
      <summary>Mission Scope &amp; Outcome Detail</summary>
      ${renderEvidenceSection("Purpose", entry.purpose_section)}
      ${renderEvidenceSection("Delivered Capability", entry.delivered_capability_section)}
      ${renderEvidenceSection("Deferred Work", entry.deferred_work_section)}
    </details>
  `;
}

// Checkpoint Change Set Detail (Mission 7) -- a third read-only
// drill-down per history entry: the repository-relative file paths Git
// itself reports as changed by that mission's published checkpoint
// commit, not anything parsed from closure-document prose. Three
// distinct, explicit states -- never conflated: an unavailable change
// set (checkpoint_changes_error set), a legitimately empty change set
// (checkpoint_changed_files === [] with no error), and a normal
// non-empty change set. Same GET /api/projects/{project_id} response,
// no new route.
function renderCheckpointChangeSet(entry) {
  let body;
  if (entry.checkpoint_changes_error) {
    body = `<p class="error-text">Checkpoint change set unavailable: ${escapeHtml(entry.checkpoint_changes_error)}</p>`;
  } else if (!Array.isArray(entry.checkpoint_changed_files)) {
    body = '<p class="error-text">Checkpoint change set unavailable.</p>';
  } else if (entry.checkpoint_changed_files.length === 0) {
    body = '<p class="error-text">This checkpoint commit changed no files.</p>';
  } else {
    const items = entry.checkpoint_changed_files
      .map((path) => `<li><code>${escapeHtml(path)}</code></li>`)
      .join("");
    body = `<ul class="change-set-list">${items}</ul>`;
  }

  return `
    <details class="evidence-details">
      <summary>Checkpoint Change Set Detail</summary>
      ${body}
    </details>
  `;
}

function renderMissionHistory(history) {
  if (!Array.isArray(history) || history.length === 0) {
    return '<p class="error-text">No mission history records found.</p>';
  }
  return `<ul class="history-list">${history.map(renderHistoryEntry).join("")}</ul>`;
}

function renderProjectDetail(snapshot) {
  const attention = snapshot.attention || { required: true, reason: "attention state unavailable" };
  const bannerClass = attention.required ? "required" : "ok";
  const bannerText = attention.required
    ? `ACTION REQUIRED — ${attention.reason || "see below"}`
    : "NO ACTION REQUIRED";

  return `
    ${BACK_LINK}
    <section class="card">
      <h2>${escapeHtml(snapshot.name)}</h2>
      <p class="summary">${escapeHtml(snapshot.state ? snapshot.state.summary.trim() : "Project state unavailable.")}</p>
      <div class="attention-banner ${bannerClass}">${escapeHtml(bannerText)}</div>
      ${renderGitStatus(snapshot.git)}
      ${renderState(snapshot.state, snapshot.state_error)}
    </section>
    <section class="card">
      <h3>Mission &amp; Checkpoint History</h3>
      ${renderMissionHistory(snapshot.mission_history)}
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
  root.innerHTML = '<p class="loading">Loading projects…</p>';
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

// Read-only client-side routing: the hash alone selects the screen, so the
// server never needs a second HTML route. `#/projects/<id>` selects the
// Project Detail screen for that id; any other hash (including none) shows
// the Projects screen. No history/back-end state is created -- this is
// pure view selection over the two static <main> containers already in
// index.html.
async function loadProjectDetail(projectId) {
  const root = document.getElementById("detail");
  root.innerHTML = `${BACK_LINK}<p class="loading">Loading project…</p>`;
  try {
    const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}`);
    if (response.status === 404) {
      root.innerHTML = `${BACK_LINK}<p class="fatal-error">Project "${escapeHtml(projectId)}" not found.</p>`;
      return;
    }
    if (!response.ok) {
      throw new Error(`request failed: ${response.status} ${response.statusText}`);
    }
    const snapshot = await response.json();
    root.innerHTML = renderProjectDetail(snapshot);
  } catch (err) {
    root.innerHTML = `${BACK_LINK}<p class="fatal-error">Failed to load project: ${escapeHtml(err.message)}</p>`;
  }
}

function parseDetailProjectId() {
  const match = /^#\/projects\/(.+)$/.exec(location.hash);
  return match ? decodeURIComponent(match[1]) : null;
}

function render() {
  const projectsView = document.getElementById("projects");
  const detailView = document.getElementById("detail");
  const projectId = parseDetailProjectId();
  if (projectId) {
    projectsView.hidden = true;
    detailView.hidden = false;
    loadProjectDetail(projectId);
  } else {
    detailView.hidden = true;
    projectsView.hidden = false;
    loadProjects();
  }
}

window.addEventListener("hashchange", render);
render();
