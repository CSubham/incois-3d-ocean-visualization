// The S6 renderer facade: the only thing S7 knows about rendering.
//
// S7 hands over renderer-independent products and declarative display state.
// Each hand-over returns its outcome at once, so S7 commits new state only for
// what is actually shown and a refused product leaves the previous one both
// displayed and described. Events carry only what happens later: pointer
// hover, a marker pick, a failed mount, a render failure or a lost context.
// No scene, material, texture or buffer object crosses this boundary, so
// another engine replaces the implementation, not the UI.
export {};
