// Shared mutable state read/written across modules (render, search).
export const state = {
    sizeMode: 'linear',       // 'linear' = faithful areas, 'log' = per-level compression
    searchHighlight: null,    // path of the tile to highlight after a search jump
    // What node sizes are counted in. It follows the dataset, not the column
    // name: the token dumps hold token counts while the per-project exports
    // hold line counts, and the selector can load either.
    unit: 'lines',
};
