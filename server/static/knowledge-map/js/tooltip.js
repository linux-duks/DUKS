import { state } from './state.js';

const tooltip = document.getElementById("tooltip");
const fmt = d3.format(",");

export function showTooltip(event, d) {
    const tf = d.data.tf != null ? (+d.data.tf).toFixed(1) : "n/a";
    const size = d.data.actual_size || `${fmt(Math.round(d._true || 0))} ${state.unit}`;
    const kind = d.children ? "Directory" : "File";
    tooltip.innerHTML =
        `<div><b>${d.data.name}</b> <span style="color:#94a3b8">(${kind})</span></div>` +
        `<div class="tt-path">${d.data.path || '/'}</div>` +
        `<div>${size} &middot; Pony Factor ${tf}</div>`;
    tooltip.style.opacity = 1;

    // Adaptive placement: default below-right of the cursor, but flip to the
    // left / above when that would overflow the viewport (bottom & right
    // edges). Measured after setting content so we know the real box size.
    const GAP = 14;
    const vw = window.innerWidth, vh = window.innerHeight;
    const tw = tooltip.offsetWidth, th = tooltip.offsetHeight;

    let left = event.clientX + GAP;
    if (left + tw > vw) left = event.clientX - GAP - tw;   // flip left
    left = Math.max(4, Math.min(left, vw - tw - 4));       // clamp

    let top = event.clientY + GAP;
    if (top + th > vh) top = event.clientY - GAP - th;     // flip above
    top = Math.max(4, Math.min(top, vh - th - 4));         // clamp

    tooltip.style.left = left + "px";
    tooltip.style.top = top + "px";
}

export function hideTooltip() {
    tooltip.style.opacity = 0;
}
