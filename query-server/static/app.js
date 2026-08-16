// Minimal vanilla-JS frontend for the /search and /suggest API. No build step,
// no framework -- this is a demo surface for the ranking pipeline, not a product.

// Matches app/main.py's default API_KEY so the bundled demo keeps working
// unmodified. This is a public demo key, not a secret -- it's sitting in this
// file, which any visitor's browser downloads in full. Its job is exercising
// real auth-enforcement code (a wrong/missing key really does get a 401), not
// protecting anything from a motivated attacker. If you set a real API_KEY via
// the environment for an actual deployment, update this constant to match (or
// better, template it into index.html server-side rather than hardcoding it
// here) -- see app/main.py's require_api_key comment for the full tradeoff.
const API_KEY = "dev-demo-key-change-me";

const form = document.getElementById("search-form");
const input = document.getElementById("query-input");
const masthead = document.getElementById("masthead");
const resultsView = document.getElementById("results-view");
const resultsList = document.getElementById("results-list");
const resultsSummary = document.getElementById("results-summary");
const btnBack = document.getElementById("btn-back");

// Tracks the query/mode behind whatever's currently on screen, so a click on
// a result can report which search produced it -- Phase 8's relevance-
// feedback signal (POST /feedback/click), the real, cheapest-available
// substitute for the click/relevance data this project didn't have before.
let currentSearch = { query: "", rerank: false };

// Event delegation: results are re-rendered wholesale on every search
// (innerHTML replace), so one listener on the container outlives any
// individual result rather than needing to be re-attached per result.
resultsList.addEventListener("click", (event) => {
  const link = event.target.closest(".result-title");
  if (!link) return;
  const docId = Number(link.dataset.docId);
  const rank = Number(link.dataset.rank);
  if (!Number.isNaN(docId) && !Number.isNaN(rank)) {
    recordClick(docId, rank);
  }
});

function recordClick(docId, rank) {
  // fire-and-forget: the link already opens in a new tab (target="_blank"),
  // so the current page never navigates away and a plain fetch() is reliable
  // here -- no need for navigator.sendBeacon's "survives page unload" behavior
  fetch("/feedback/click", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
    body: JSON.stringify({
      query: currentSearch.query, doc_id: docId, rank,
      rerank: currentSearch.rerank,
    }),
  }).catch(() => {
    // best-effort only -- a failed click log should never be visible to the
    // user or block them from following the link they just clicked
  });
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  // event.submitter is whichever <button type="submit"> was actually clicked
  // (or the first one, if Enter was pressed in the input) -- its `value`
  // attribute tells us lexical vs. semantic without a separate toggle control.
  const mode = event.submitter ? event.submitter.value : "lexical";
  const query = input.value.trim();
  if (query) runSearch(query, mode === "semantic");
});

btnBack.addEventListener("click", () => {
  resultsView.hidden = true;
  masthead.classList.remove("compact");
  input.focus();
});

async function runSearch(query, rerank) {
  currentSearch = { query, rerank };
  showCompactHeader();
  resultsList.innerHTML = '<p class="empty-state">Searching…</p>';
  resultsView.hidden = false;

  const params = new URLSearchParams({ q: query, page_size: "10", rerank: String(rerank) });
  let data;
  try {
    const response = await fetch(`/search?${params}`, { headers: { "X-API-Key": API_KEY } });
    data = await response.json();
    if (!response.ok) {
      renderError(data.detail || "Something went wrong.");
      return;
    }
  } catch (err) {
    renderError("Could not reach the server. Is it running?");
    return;
  }

  renderResults(query, rerank, data);
}

function showCompactHeader() {
  masthead.classList.add("compact");
}

function renderError(message) {
  resultsSummary.textContent = "";
  resultsList.innerHTML = `<p class="error-state">${escapeHtml(message)}</p>`;
}

function renderResults(query, rerank, data) {
  const mode = rerank ? "Semantic Search" : "Search";
  const total = data.total_results ?? 0;

  resultsSummary.innerHTML =
    `<b>${mode}</b> &middot; search results for &ldquo;${escapeHtml(query)}&rdquo; ` +
    `&middot; ${total} result${total === 1 ? "" : "s"}`;

  if (data.message && (!data.results || data.results.length === 0)) {
    let detail = escapeHtml(data.message);
    if (data.unknown_words && data.unknown_words.length) {
      detail += ` (unrecognized: ${data.unknown_words.map(escapeHtml).join(", ")})`;
    }
    resultsList.innerHTML = `<p class="empty-state">${detail}</p>`;
    return;
  }

  if (data.did_you_mean) {
    resultsSummary.innerHTML += `<br>Did you mean: <i>${escapeHtml(data.did_you_mean)}</i>?`;
  }

  if (!data.results || data.results.length === 0) {
    resultsList.innerHTML = '<p class="empty-state">No results found.</p>';
    return;
  }

  resultsList.innerHTML = data.results.map((result, i) => renderResult(result, i + 1)).join("");
}

function renderResult(result, rank) {
  // A result with no bm25/pagerank score at all was found purely by semantic
  // augmentation -- BM25 never retrieved it. Worth surfacing, not hiding: it's
  // the clearest possible demonstration that the semantic layer isn't just
  // reordering the same documents BM25 already found.
  const isAugmented = result.bm25_score === null && result.pagerank_score === null && result.semantic_score !== null;

  return `
    <article class="result">
      <div class="result-title-row">
        <span class="result-rank">${rank}.</span>
        <a class="result-title" href="${escapeAttr(result.url || "#")}" target="_blank" rel="noopener"
           data-doc-id="${result.doc_id}" data-rank="${rank}">
          ${escapeHtml(result.title || "(untitled)")}
        </a>
        ${isAugmented ? '<span class="augmented-badge">found by meaning</span>' : ""}
      </div>
      ${result.url ? `<div class="result-url">${escapeHtml(result.url)}</div>` : ""}
      ${result.snippet ? `<p class="result-snippet">${result.snippet}</p>` : ""}
      ${renderWhyResult(result)}
    </article>
  `;
}

// The "killer feature": an expandable, honest breakdown of what actually drove
// this result's rank. A signal that's null (never evaluated this doc) renders
// as "not evaluated," never as a fake 0 -- treating "never scored" the same as
// "scored zero" would misrepresent what actually happened during ranking.
function renderWhyResult(result) {
  const rows = [
    signalRow("Lexical match (BM25)", "bm25", result.bm25_score),
    signalRow("Semantic match", "semantic", result.semantic_score),
    signalRow("Authority (PageRank)", "pagerank", result.pagerank_score),
  ].join("");

  return `
    <details class="why-result">
      <summary>Why this result?</summary>
      <div class="why-body">
        ${rows}
        <div class="final-score-row">
          <span>Final score</span>
          <span>${result.score.toFixed(3)}</span>
        </div>
      </div>
    </details>
  `;
}

function signalRow(label, cssClass, value) {
  const known = value !== null && value !== undefined;
  const pct = known ? Math.max(0, Math.min(1, value)) * 100 : 0;
  const valueText = known ? value.toFixed(3) : "n/a";
  return `
    <div class="signal-row">
      <span class="signal-label">${label}</span>
      <div class="signal-track"><div class="signal-fill ${cssClass}" style="width:${pct}%"></div></div>
      <span class="signal-value ${known ? "" : "na"}">${valueText}</span>
    </div>
  `;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function escapeAttr(str) {
  return escapeHtml(str).replace(/"/g, "&quot;");
}
