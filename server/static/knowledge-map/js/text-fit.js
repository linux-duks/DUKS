import { FONT_STACK, MIN_FONT, MIN_LINE_CHARS } from './config.js';

// Text measurement via canvas -- fast and, unlike getComputedTextLength(),
// it does NOT force an SVG layout reflow, so it's safe to call per-tile.
const measureCtx = document.createElement('canvas').getContext('2d');

function textWidthPerPx(text, weight) {
    measureCtx.font = `${weight} 10px ${FONT_STACK}`;   // width scales linearly with size
    return measureCtx.measureText(text).width / 10;
}

// Largest font-size <= std that fits `text` within availW and one line in
// availH. Returns 0 if it can't reach MIN_FONT (caller then hides the label).
export function fitFontSize(text, std, availW, availH, weight) {
    if (!text || availW <= 2 || availH <= 2) return 0;
    const byWidth = availW / textWidthPerPx(text, weight);
    const size = Math.min(std, byWidth, availH);
    return size >= MIN_FONT ? size : 0;
}

function measureWidth(text, fontSize, weight) {
    measureCtx.font = `${weight} ${fontSize}px ${FONT_STACK}`;
    return measureCtx.measureText(text).width;
}

// Greedy word-wrap `name` into lines that each fit `availW` at `fontSize`.
// Breaks preferentially at path-ish separators (/ _ - .); hard-breaks any
// single token still too wide to fit on its own line.
function wrapName(name, availW, fontSize) {
    const tokens = name.match(/[^/_.\-]+|[/_.\-]+/g) || [name];
    const lines = [];
    let cur = "";
    for (let tok of tokens) {
        if (cur && measureWidth(cur + tok, fontSize, 600) > availW) {
            lines.push(cur); cur = "";
        }
        cur += tok;
        // Hard-break a token wider than the whole line.
        while (measureWidth(cur, fontSize, 600) > availW && cur.length > 1) {
            let lo = 1, hi = cur.length, fit = 1;
            while (lo <= hi) {
                const mid = (lo + hi) >> 1;
                if (measureWidth(cur.slice(0, mid), fontSize, 600) <= availW) { fit = mid; lo = mid + 1; }
                else hi = mid - 1;
            }
            lines.push(cur.slice(0, fit));
            cur = cur.slice(fit);
        }
    }
    if (cur) lines.push(cur);
    return lines;
}

// Largest size (<= std) at which `name` fits availW x availH *with wrapping*.
// For tall/narrow tiles this uses the height to keep a bigger font across
// multiple lines instead of shrinking to a tiny single line. Returns
// {size, lines} or null if it can't fit even at MIN_FONT.
export function fitWrapped(name, std, availW, availH, maxLinesCap) {
    if (!name || availW <= 2 || availH <= 2) return null;
    const top = Math.min(std, Math.floor(availH));
    for (let s = top; s >= MIN_FONT; s--) {
        const lineH = s * 1.18;
        const maxLines = Math.max(1, Math.min(maxLinesCap, Math.floor(availH / lineH)));
        const lines = wrapName(name, availW, s);
        if (lines.length > maxLines) continue;
        // Reject "shredded" multi-line results on very narrow tiles (e.g.
        // "ato"/"mbi"/"os."/"h"). A single line at any size is always fine;
        // wrapping is only kept if its longest line stays readable.
        const longest = Math.max(...lines.map(l => l.length));
        if (lines.length === 1 || longest >= MIN_LINE_CHARS) return { size: s, lines };
    }
    return null;
}
