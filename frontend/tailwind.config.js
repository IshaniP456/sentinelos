/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Warm charcoal "command center" surfaces (not the generic navy/slate).
        ink: {
          900: '#0a0a0c',
          800: '#111013',
          700: '#17161a',
          600: '#201e24',
          500: '#2c2a31',
          400: '#3a3742',
        },
        // Signature brand accent — warm gold (distinctive, "sentinel").
        brand: {
          DEFAULT: '#f5b43c',
          bright: '#ffc74d',
          dim: '#b4812a',
        },
        // Refined status language (contract §4.1).
        status: {
          green: '#34d399',
          amber: '#f59e0b',
          red: '#fb5a5a',
          blue: '#6aa8ff',
          gray: '#7c7a85',
        },
      },
      fontFamily: {
        display: ['"Space Grotesk"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      boxShadow: {
        glow: '0 0 0 1px rgba(245,180,60,0.25), 0 0 24px -4px rgba(245,180,60,0.35)',
        card: '0 1px 0 0 rgba(255,255,255,0.03) inset, 0 20px 40px -24px rgba(0,0,0,0.8)',
      },
      keyframes: {
        glowpulse: {
          '0%,100%': { opacity: '0.55' },
          '50%': { opacity: '1' },
        },
        floaty: {
          '0%,100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-4px)' },
        },
      },
      animation: {
        glowpulse: 'glowpulse 2.4s ease-in-out infinite',
        floaty: 'floaty 6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
