import { HEADER_H } from './config.js';
import { state } from './state.js';
import { initRenderer } from './render.js';
import { setupSearch } from './search.js';

const container = document.getElementById("chart");
const width = container.parentElement.clientWidth;
const height = container.parentElement.clientHeight - 46;

const loadingEl = document.getElementById('loading');
const repoSelect = document.getElementById('repo-select');

// Collapsed explainer: the toggle lives inline in the subtitle so the treemap
// keeps its position on load, and only moves down if the reader asks for it.
const introToggle = document.getElementById('intro-toggle');
const introBox = document.getElementById('intro');
introToggle.addEventListener('click', ev => {
    ev.preventDefault();
    const open = introBox.hasAttribute('hidden');
    introBox.toggleAttribute('hidden', !open);
    introToggle.setAttribute('aria-expanded', String(open));
});

const treemap = d3.treemap()
    .paddingOuter(2)
    .paddingTop(HEADER_H)
    .paddingInner(2)
    .round(true);

// The one live renderer; replaced wholesale whenever a repository is loaded.
let setSizeMode = () => { };
let search = null;
// Bumped per load so a slow fetch that lost the race (user switched repos
// again while it was in flight) discards its result instead of overwriting
// the newer tree.
let loadToken = 0;

function showLoading(msg) {
    loadingEl.classList.remove('error');
    loadingEl.textContent = msg;
    loadingEl.style.display = 'flex';
}

function showError(msg) {
    loadingEl.classList.add('error');
    loadingEl.textContent = msg;
    loadingEl.style.display = 'flex';
}

// Each load draws into a brand-new <svg>. Cheaper than it sounds, and it is
// what makes switching repos safe: the previous renderer's progressive
// appendDepth pass may still have frames queued, and its data-join is keyed by
// path -- paths repeat across repositories, so reusing the element would let
// stale tiles resurrect against unrelated data. Handing the old renderer a
// detached node lets it finish writing into nothing, and be collected.
function freshSvg() {
    d3.select("#chart").selectAll("svg").remove();
    return d3.select("#chart").append("svg")
        .attr("viewBox", [0, 0, width, height])
        .attr("width", width)
        .attr("height", height)
        .style("overflow", "hidden");
}

function loadRepo(repo) {
    const token = ++loadToken;
    showLoading('Calculating Full Project Layout...');
    document.getElementById('bc-text').textContent = 'Fetching data...';
    repoSelect.disabled = true;

    const url = repo
        ? `/api/knowledge-map/tree?repo=${encodeURIComponent(repo)}`
        : '/api/knowledge-map/tree';

    return d3.json(url).then(data => {
        if (token !== loadToken) return;   // a newer load superseded this one

        // Build the full hierarchy once; .sum() over leaf values gives correct
        // areas for every ancestor (directory node_len_lines == sum of leaves).
        const rootHierarchy = d3.hierarchy(data)
            .sum(d => d.value || 0)
            .sort((a, b) => (b.value || 0) - (a.value || 0));

        state.searchHighlight = null;      // belongs to the tree we just dropped
        state.unit = data.unit || 'lines'; // tokens or lines, depending on the dataset
        const svg = freshSvg();

        const renderer = initRenderer(rootHierarchy, svg, treemap, width, height);
        setSizeMode = renderer.setSizeMode;
        renderer.render(rootHierarchy);

        // ---- Search ------------------------------------------------------
        // Every node is already in memory; pre-lowercase name/path for matching.
        const allNodes = rootHierarchy.descendants();
        for (const n of allNodes) {
            n._sname = (n.data.name || "").toLowerCase();
            n._spath = (n.data.path || "").toLowerCase();
        }

        // Listeners are attached on the first load only; later loads just swap
        // the node list and renderer behind them.
        if (search) search.setData(allNodes, renderer.render);
        else search = setupSearch(allNodes, renderer.render);

        loadingEl.style.display = 'none';
        repoSelect.disabled = false;
    }).catch(err => {
        if (token !== loadToken) return;
        console.error(err);
        // Without this the overlay just sat on "Calculating..." forever.
        showError(`Could not load ${repo || 'the default repository'}. ` +
            `Check that its CSV is present and well-formed.`);
        repoSelect.disabled = false;
    });
}

// Populate the selector, then load whichever repository it lands on.
d3.json('/api/knowledge-map/repos').then(({ repos, default: fallback }) => {
    repoSelect.innerHTML = "";
    for (const name of repos) {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        repoSelect.appendChild(opt);
    }
    const initial = repos.includes(fallback) ? fallback : (repos[0] || "");
    repoSelect.value = initial;
    repoSelect.addEventListener('change', () => loadRepo(repoSelect.value));
    return loadRepo(initial);
}).catch(err => {
    console.error(err);
    showError('Could not list repositories (/api/knowledge-map/repos failed).');
});

// Toggle between faithful and compressed sizing; re-render the current view.
// Wired once -- setSizeMode points at whichever renderer is live.
document.querySelectorAll('input[name="sizemode"]').forEach(el => {
    el.addEventListener('change', ev => {
        if (ev.target.checked) setSizeMode(ev.target.value);
    });
});
