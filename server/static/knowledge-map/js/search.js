import { state } from './state.js';

const fmt = d3.format(",");

const escapeHtml = s => (s || "").replace(/[&<>"]/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// Wires up the search box against the full (pre-lowercased) node list and
// drives `render` to jump to whatever the user picks. Returns `setData`, used
// when a different repository is loaded: the DOM listeners below are attached
// once and then re-pointed at the new node list / renderer, instead of calling
// setupSearch again (which would stack a second set of listeners, leaving the
// previous repo's tree searchable alongside the current one).
export function setupSearch(allNodes, render) {
    const searchInput = document.getElementById("search");
    const resultsBox = document.getElementById("search-results");
    let results = [], activeIdx = -1, searchTimer = null;

    function setData(nextNodes, nextRender) {
        allNodes = nextNodes;
        render = nextRender;
        clearTimeout(searchTimer);
        searchInput.value = "";
        closeResults();
    }

    function doSearch(raw) {
        const q = raw.trim().toLowerCase();
        activeIdx = -1;
        if (!q) { closeResults(); return; }
        const scored = [];
        for (const n of allNodes) {
            if (n.depth === 0) continue;
            const i = n._sname.indexOf(q);
            let score;
            if (i === 0) score = (n._sname === q) ? 0 : 1;   // exact / prefix
            else if (i > 0) score = 2;                       // name contains
            else if (n._spath.indexOf(q) >= 0) score = 3;    // path contains
            else continue;
            scored.push({ n, score });
        }
        scored.sort((a, b) => a.score - b.score || a.n._sname.length - b.n._sname.length);
        results = scored.slice(0, 25).map(s => s.n);
        renderResults();
    }

    function renderResults() {
        if (!results.length) {
            resultsBox.innerHTML = '<div class="sr-empty">No matches</div>';
            resultsBox.classList.add("open");
            return;
        }
        resultsBox.innerHTML = results.map((n, idx) => {
            const kind = n.children ? "folder" : "file";
            const size = n.data.actual_size || `${fmt(Math.round(n.value || 0))} ${state.unit}`;
            return `<div class="sr-item${idx === activeIdx ? ' active' : ''}" data-idx="${idx}">
                <div class="sr-name">${escapeHtml(n.data.name)}<span class="kind">${kind} &middot; ${size}</span></div>
                <div class="sr-path">${escapeHtml(n.data.path)}</div></div>`;
        }).join("");
        resultsBox.classList.add("open");
        resultsBox.querySelectorAll(".sr-item").forEach(el => {
            el.addEventListener("click", () => selectResult(results[+el.dataset.idx]));
        });
    }

    function moveActive(dir) {
        if (!results.length) return;
        activeIdx = (activeIdx + dir + results.length) % results.length;
        resultsBox.querySelectorAll(".sr-item").forEach((el, i) =>
            el.classList.toggle("active", i === activeIdx));
        const act = resultsBox.querySelector(".sr-item.active");
        if (act) act.scrollIntoView({ block: "nearest" });
    }

    function selectResult(n) {
        if (!n) return;
        state.searchHighlight = n.data.path;
        // Directory -> zoom into it; file -> reveal its containing folder and
        // highlight the file tile. (Never cull the highlighted target.)
        const focus = (n.children && n.children.length) ? n : (n.parent || n);
        closeResults();
        searchInput.blur();
        render(focus);
    }

    function closeResults() {
        resultsBox.classList.remove("open");
        resultsBox.innerHTML = "";
        results = []; activeIdx = -1;
    }

    searchInput.addEventListener("input", () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => doSearch(searchInput.value), 120);
    });
    searchInput.addEventListener("keydown", ev => {
        if (ev.key === "ArrowDown") { ev.preventDefault(); moveActive(1); }
        else if (ev.key === "ArrowUp") { ev.preventDefault(); moveActive(-1); }
        else if (ev.key === "Enter") { ev.preventDefault(); selectResult(results[activeIdx] || results[0]); }
        else if (ev.key === "Escape") { closeResults(); searchInput.blur(); }
    });
    document.addEventListener("click", ev => {
        if (!ev.target.closest(".search-wrap")) closeResults();
    });

    return { setData };
}
