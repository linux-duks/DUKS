// Per-level normalization. Walks the tree top-down and splits each node's
// allocated value among its children in proportion to f(child.trueSize),
// normalized so the children always sum to exactly the parent's value.
// This keeps d3.treemap's parent == Σchildren requirement intact (gap-free
// tiling) while letting f compress the dynamic range one level at a time.
//   - 'linear': f = identity  ->  reproduces true, globally faithful areas.
//   - 'log':    f = log(1+x)  ->  small siblings stay visible next to giants,
//               and because f is applied to true aggregate sizes (not summed
//               leaves), it encodes size, never file count.
export function applyWeights(root, mode) {
    const f = mode === 'log' ? (v => Math.log1p(v)) : (v => v);
    root.value = root._true || 0;
    root.eachBefore(node => {
        const kids = node.children;
        if (!kids || !kids.length) return;
        
        const weights = kids.map(c => f(c._true || 0));
        let tot = 0;
        for (const w of weights) tot += w;
        const parentVal = node.value || 0;
        

        // in case of no children (or all children have no lines), we divide the parent's value envely
        if (tot == 0) {
            const each = parentVal / kids.length;
            kids.forEach(c => { c.value = each; });
        } else {
            
            // normalize so the children sum to the parent's value
            kids.forEach((c, i) => { c.value = parentVal * weights[i] / tot; });
        }
    });
}
