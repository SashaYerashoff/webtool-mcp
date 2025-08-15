/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{ts,tsx,jsx,js}'
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          'Inter',
          'Noto Sans',
          'ui-sans-serif',
          'system-ui',
          'Segoe UI',
          'Roboto',
          'Helvetica Neue',
          'Arial',
          'Noto Sans',
          'sans-serif',
          'Apple Color Emoji',
          'Segoe UI Emoji',
          'Segoe UI Symbol'
        ],
        news: [
          'Newsreader',
          'Georgia',
          'Times New Roman',
          'serif'
        ]
      },
      colors: {
        brand: {
          50: '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a'
        },
        paper: {
          50: '#f9f4ea',
          100: '#f3ead9',
          200: '#e9dcc4',
          300: '#dfcfb2',
          400: '#d2bea0',
          500: '#c7b18f'
        },
        ink: {
          900: '#0f0d0a',
          800: '#17130f',
          700: '#201a14',
          600: '#2a241d',
          500: '#3a3127'
        },
        rust: {
          50: '#f9eee8',
          100: '#f1d8cc',
          200: '#e5b9a7',
          300: '#d9927c',
          400: '#cd6f53',
          500: '#c45f42',
          600: '#b4572e',
          700: '#984b22',
          800: '#7c3f1a',
          900: '#613216'
        }
      }
    }
  },
  plugins: []
}
