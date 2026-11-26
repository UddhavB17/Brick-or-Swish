/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_FLAGSMITH_ENVIRONMENT_KEY?: string;
  readonly VITE_FLAGSMITH_API?: string;
  readonly VITE_FLAGSMITH_EVENTS_API?: string;
  readonly VITE_FORCE_MISS_FEEDBACK?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
