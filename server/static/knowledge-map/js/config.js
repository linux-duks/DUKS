export const MAX_DEPTH = 3;        // how many nested levels to draw at once (Plotly-style)
export const HEADER_H = 20;        // pixels reserved at the top of a directory tile for its label
export const MIN_PX = 2;           // don't render tiles smaller than this (invisible + unclickable)
export const MIN_FONT = 3;         // labels shrink to fit down to this size, else are hidden
export const STD_DIR_FONT = 12;    // preferred directory-label size when it fits
export const STD_LEAF_FONT = 11;   // preferred leaf-label size when it fits
export const MIN_LINE_CHARS = 4;   // don't wrap into lines shorter than this (avoids shredding)
export const HEAVY_TILES = 1250;   // above this many tiles, snap geometry instead of tweening it
export const LAYOUT_CACHE_MAX = 24; // how many computed subtree layouts to keep (LRU). An entry holds
                                    // every node of its subtree, so this bounds memory, not just count:
                                    // 24 full entries measured ~50MB extra heap on the kernel dataset.

export const FONT_STACK = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
