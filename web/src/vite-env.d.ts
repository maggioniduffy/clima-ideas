/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the published static layers (R2); empty or unset = local FastAPI via the /api proxy. */
  readonly VITE_DATA_URL?: string;
}
