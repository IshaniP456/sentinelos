/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Enterprise dark surfaces
        ink: {
          900: '#0a0e17',
          800: '#0f1420',
          700: '#161c2b',
          600: '#1e2740',
          500: '#2a3450',
        },
        // Status language (see integration contract §4.1)
        status: {
          green: '#22c55e',
          amber: '#f59e0b',
          red: '#ef4444',
          blue: '#3b82f6',
          gray: '#64748b',
        },
      },
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
}
