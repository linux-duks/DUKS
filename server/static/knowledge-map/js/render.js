import { MAX_DEPTH, HEADER_H, MIN_PX, STD_DIR_FONT, STD_LEAF_FONT, HEAVY_TILES, LAYOUT_CACHE_MAX } from './config.js';
import { state } from './state.js';
import { applyWeights } from './weights.js';
import { fitFontSize, fitWrapped } from './text-fit.js';
import { showTooltip, hideTooltip } from './tooltip.js';

const fmt = d3.format(",");

function fullPath(node) {
    return node.ancestors().reverse().map(a => a.data.name).join(" / ");
}

function nodeClass(d) {
    return "node " + (d.children ? "internal" : "leaf") +
        (d.data.path === state.searchHighlight ? " hl" : "");
}

function cssId(path) {
    return (path || "root").replace(/[^a-zA-Z0-9_-]/g, "_");
}

// Builds the `render(focus)` function bound to one SVG/hierarchy, keeping
// currentFocus/renderToken private to this closure. Returns `render` plus
// `setSizeMode`, the only other way callers should affect layout.
export function initRenderer(rootHierarchy, svg, treemap, width, height) {
    let currentFocus = null;   // the node currently zoomed into (for re-render on toggle)
    let renderToken = 0;       // bumps each render so a stale progressive pass can bail out

    // path -> node index over the full (un-capped) hierarchy, walked once here
    // (~27ms for 67k nodes) instead of on every click. Paths are already this
    // app's node key (data-join, search highlight, tooltip), so one entry per
    // node is all the drill-down lookup below needs. Last entry wins on a
    // duplicate path, matching the scan this replaces (it never early-exited).
    const byPath = new Map();
    rootHierarchy.each(n => byPath.set(n.data.path, n));

    // Locate a node by path within the full (un-capped) hierarchy so we can
    // drill past the depth cap.
    function findInFull(path) {
        return byPath.get(path) || null;
    }

    function render(focus) {
        currentFocus = focus;
        const token = ++renderToken;   // invalidates any in-flight progressive pass

        // Re-layout the focused subtree to fill the canvas each drill-down,
        // so deep trees stay legible instead of being rescaled from a tiny box.
        // Memoized (see getLayout): revisiting a node recomputes nothing.
        const local = getLayout(focus);

        // Draw the focus subtree down to MAX_DEPTH levels, skipping tiles too
        // small to see or click. Safe because a child is always smaller than
        // its parent (no orphans), and drilling in re-fills the canvas so these
        // become visible again. Cuts thousands of sub-pixel slivers at big nodes.
        const visible = local.descendants().filter(n =>
            n.depth > 0 && n.depth <= MAX_DEPTH &&
            ((n.x1 - n.x0) >= MIN_PX && (n.y1 - n.y0) >= MIN_PX
                || n.data.path === state.searchHighlight));   // never cull the search target

        // Adaptive animation: on big views (root, large dirs) tweening the
        // geometry of thousands of rects is where the jank lives -- and the eye
        // can't track that many simultaneous tweens anyway. So snap geometry
        // instantly and keep only a quick opacity fade. Small drills keep the
        // full, perceptible ease.
        const heavy = visible.length > HEAVY_TILES;
        const geomDur = heavy ? 0 : 500;
        const fadeDur = heavy ? 150 : 500;

        // Breadcrumb reflects the *focused* node within the full tree.
        const bcText = document.getElementById('bc-text');
        bcText.innerHTML = `<b>${fullPath(focus) || 'Project Root'}</b>` +
            ` &nbsp;|&nbsp; ${fmt(Math.round(focus.value || 0))} ${state.unit}`;
        document.getElementById('breadcrumb').onclick = () => {
            if (focus.parent) { state.searchHighlight = null; render(focus.parent); }
        };

        // Positions/sizes/labels for any selection (freshly entered or persisting).
        function positionNodes(sel) {
            sel.attr("class", nodeClass);

            // Opacity always animates -- it's composited, so it's cheap even on
            // thousands of nodes.
            sel.transition("fade").duration(fadeDur).style("opacity", 1);

            const rect = sel.select("rect")
                .attr("fill", d => d.data.color || "#cbd5e1")
                .attr("fill-opacity", d => d.children ? 0.55 : 0.92);

            if (geomDur === 0) {
                // Heavy view: set geometry directly (no per-element transition
                // scheduling) so the paint lands in one snap.
                sel.attr("transform", d => `translate(${d.x0},${d.y0})`);
                rect.attr("width", d => Math.max(0, d.x1 - d.x0))
                    .attr("height", d => Math.max(0, d.y1 - d.y0));
            } else {
                sel.transition("move").duration(geomDur).ease(d3.easeCubicOut)
                    .attr("transform", d => `translate(${d.x0},${d.y0})`);
                rect.transition("size").duration(geomDur)
                    .attr("width", d => Math.max(0, d.x1 - d.x0))
                    .attr("height", d => Math.max(0, d.y1 - d.y0));
            }

            sel.select("clipPath rect")
                .attr("width", d => Math.max(0, d.x1 - d.x0))
                .attr("height", d => Math.max(0, d.y1 - d.y0));
            sel.select("text.hdr")
                .attr("clip-path", d => `url(#clip-${cssId(d.data.path)})`)
                .each(function (d) {
                    const w = d.x1 - d.x0, h = d.y1 - d.y0;
                    const t = d3.select(this);
                    t.selectAll("tspan").remove();
                    if (d.children) {
                        // Directory: label sits in the fixed-height header band,
                        // so only width binds -- shrink to fit down to MIN_FONT.
                        t.attr("class", "hdr name-label");
                        const size = fitFontSize(d.data.name, STD_DIR_FONT, w - 8, HEADER_H - 5, 600);
                        if (size > 0) {
                            t.append("tspan").attr("x", 5).attr("y", size + 3)
                                .style("font-size", size + "px").text(d.data.name);
                        }
                    } else {
                        // Leaf: constrained by width AND height. Wrap the name across
                        // lines so tall/narrow tiles keep a readable font instead of
                        // shrinking to a sliver. Add the TF line if room remains below.
                        t.attr("class", "hdr leaf-label");
                        const res = fitWrapped(d.data.name, STD_LEAF_FONT, w - 8, h - 4, 6);
                        if (res) {
                            const { size, lines } = res;
                            const lineH = size * 1.18;
                            const baseY = size + 2;
                            lines.forEach((ln, i) => {
                                t.append("tspan").attr("x", 5).attr("y", baseY + i * lineH)
                                    .style("font-size", size + "px").text(ln);
                            });
                            const lastBottom = baseY + (lines.length - 1) * lineH;
                            const ms = Math.min(10, size);
                            if (d.data.tf != null && h >= lastBottom + ms + 3) {
                                t.append("tspan").attr("class", "meta-label")
                                    .attr("x", 5).attr("y", lastBottom + ms + 2)
                                    .style("font-size", ms + "px")
                                    .text(`TF ${(+d.data.tf).toFixed(1)}`);
                            }
                        }
                    }
                });
        }

        // Cancel any transitions still in flight from a previous (possibly
        // interrupted) render before re-binding. Without this, zooming in then
        // back out before the drill finishes leaves half-loaded child tiles
        // animating toward their old canvas-filling geometry -- a running tween
        // keeps overwriting the geometry we set here (especially on the heavy
        // path, which assigns attrs directly rather than via a transition),
        // leaving artifacts over the parent. Interrupting also cancels a pending
        // exit .remove() so a node that becomes valid again here isn't deleted.
        svg.selectAll("g.node").interrupt().interrupt("fade").interrupt("move");
        svg.selectAll("g.node rect").interrupt("size");

        // Single keyed join over the whole visible set. Stale nodes (from a
        // previous focus/mode) exit once; nodes that persist are repositioned
        // immediately (cheap attr updates -> smooth morph on toggle). Brand-new
        // nodes are appended ONE DEPTH LEVEL PER FRAME, so level 1 paints right
        // away instead of the browser blocking while it builds ~15k tiles in a
        // single synchronous pass. Deeper levels are appended later => they land
        // later in the DOM and correctly paint on top of their parents.
        const group = svg.selectAll("g.node").data(visible, d => d.data.path);
        if (heavy) group.exit().remove();
        else group.exit().transition().duration(300).style("opacity", 0).remove();
        positionNodes(group);

        const enterSel = group.enter();

        function appendDepth(depth) {
            if (token !== renderToken) return;   // a newer render superseded us
            const g = enterSel.filter(d => d.depth === depth).append("g")
                .attr("class", nodeClass)
                .style("opacity", 0)
                .attr("transform", d => `translate(${d.x0},${d.y0})`)
                .on("mousemove", showTooltip)
                .on("mouseleave", hideTooltip)
                .on("click", (event, d) => {
                    event.stopPropagation();
                    // Drill into any directory (has children in the full tree,
                    // even if we hit the depth cap here).
                    const target = findInFull(d.data.path);
                    if (target && target.children && target.children.length) {
                        state.searchHighlight = null;
                        render(target);
                    }
                });
            g.append("rect");
            g.append("clipPath").attr("id", d => "clip-" + cssId(d.data.path))
                .append("rect");
            g.append("text").attr("class", "hdr");
            positionNodes(g);

            if (depth < MAX_DEPTH) requestAnimationFrame(() => appendDepth(depth + 1));
        }

        appendDepth(1);
    }

    // ---- Layout cache ---------------------------------------------------
    // Computing a focused subtree's layout (hierarchy + sum + sort +
    // applyWeights + treemap) is a pure function of (focus, sizeMode, canvas):
    // the same three inputs always produce the exact same geometry. But we
    // recompute it constantly -- clicking the breadcrumb back out, re-entering
    // a directory visited earlier, or toggling linear/log back to a combination
    // already seen all redo identical work. So keep the finished hierarchy.
    //
    // Bounded with LRU, because an entry holds *every* node of its subtree,
    // not just the tiles drawn (~67k node objects for the root of the kernel
    // dataset) -- an unbounded cache would grow into a memory leak over a long
    // drill-down session. A Map iterates in insertion order, which gives LRU
    // almost for free: delete + re-set on a hit moves an entry to the newest
    // end, so the oldest key is always `keys().next().value` and can be
    // dropped once we exceed capacity.
    const layoutCache = new Map();

    function layoutKey(focus) {
        // sizeMode belongs in the key: it changes every node's weight, hence
        // the geometry. width/height are included so layouts computed for one
        // canvas size aren't reused for another; if a future resize handler
        // changes the canvas size, it should recreate the renderer (or update
        // width/height) so getLayout() recomputes with the new dimensions.
        // state.searchHighlight deliberately is NOT in the key: it affects
        // only the visibility filter and the "hl" class, never the layout, and
        // render() recomputes both on every pass -- including on a cache hit --
        // so a cached hierarchy can still reveal/highlight whichever tile the
        // current search asks for.
        return `${width}x${height}|${state.sizeMode}|${focus.data.path}`;
    }

    function getLayout(focus) {
        const key = layoutKey(focus);
        const cached = layoutCache.get(key);
        if (cached) {
            layoutCache.delete(key);
            layoutCache.set(key, cached);   // re-insert => most recently used
            return cached;
        }

        const local = d3.hierarchy(focus.data).sum(d => d.value || 0);
        // Keep every node's TRUE aggregate size (linear, additive) for the
        // breadcrumb/weights; d3's .value gets overwritten with layout weights.
        local.each(d => { d._true = d.value || 0; });
        local.sort((a, b) => b._true - a._true);

        // Assign per-level layout weights. 'linear' reproduces true areas
        // exactly; 'log' compresses each node relative to its siblings while
        // preserving the parent == Σchildren invariant at every level, so the
        // tiling stays gap-free and never rewards file count.
        applyWeights(local, state.sizeMode);

        treemap.size([width, height])(local);

        // Safe to hand the same node objects out again later: render() only
        // *reads* them (d3's data-join stores the datum on the element, it
        // doesn't write back to it), and every miss builds a fresh
        // d3.hierarchy, so entries never share node objects with each other or
        // with rootHierarchy -- only the read-only .data payloads underneath.
        layoutCache.set(key, local);
        while (layoutCache.size > LAYOUT_CACHE_MAX) {
            layoutCache.delete(layoutCache.keys().next().value);   // evict LRU
        }
        return local;
    }

    function setSizeMode(mode) {
        state.sizeMode = mode;
        if (currentFocus) render(currentFocus);
    }

    return { render, setSizeMode };
}
