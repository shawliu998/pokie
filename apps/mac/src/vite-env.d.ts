/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_QURIO_GUIDED_DEMO_RUN_ID?: string;
  readonly VITE_QURIO_GUIDED_DEMO_LABEL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
