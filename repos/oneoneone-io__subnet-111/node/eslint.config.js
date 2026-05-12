import eslintPluginUnicorn from 'eslint-plugin-unicorn';
import globals from 'globals';
import pluginJest from 'eslint-plugin-jest';

export default [
	eslintPluginUnicorn.configs.recommended,
  pluginJest.configs['flat/recommended'],
	{
		languageOptions: {
			globals: globals.builtin,
		},
		rules: {
			'unicorn/no-unused-properties': 'error',
			'no-console': 'error',
			'no-multiple-empty-lines': ['error', { 'max': 1, 'maxBOF': 1 }],
			'no-unused-vars': 'error',
		},
	},
	{
		ignores: [
			'**/node_modules/**',
			'**/coverage/**',
		],
	},
];
