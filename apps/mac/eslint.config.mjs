import js from '@eslint/js';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['dist/**', 'node_modules/**', 'playwright-report/**'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  { files: ['e2e/**/*.mjs'], languageOptions: { globals: { Buffer: 'readonly', URL: 'readonly', process: 'readonly' } } },
  { rules: { '@typescript-eslint/no-explicit-any': 'error', '@typescript-eslint/consistent-type-imports': ['error', { prefer: 'type-imports' }] } }
);
