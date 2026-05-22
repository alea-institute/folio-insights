// Phase 03.5: SPA mode for adapter-static. Disabling SSR makes every route
// client-rendered against the fallback shell (build/index.html), served by
// FastAPI StaticFiles. This restores the v1.1 deploy model (the v2.0 adapter-node
// SSR experiment was never deployed). Full SSR returns for the Phase 20 GA cut.
export const ssr = false;
export const prerender = false;
