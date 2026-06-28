import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default [
  {
    ignores: ["dist/**", "node_modules/**", "src-tauri/**"],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.ts", "src/**/*.tsx", "vite.config.ts"],
    languageOptions: {
      globals: {
        clearTimeout: "readonly",
        document: "readonly",
        setTimeout: "readonly",
      },
    },
    rules: {
      // Honour the `_`-prefix convention for intentionally-unused bindings
      // (e.g. `for await (const _event of ...)`, mock generator params).
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
        },
      ],
    },
  },
];
