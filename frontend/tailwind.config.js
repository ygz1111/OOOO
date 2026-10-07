/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: 'var(--workspace-bg)',
        surface: {
          DEFAULT: 'var(--surface)',
          raised: 'var(--surface-raised)',
          muted: 'var(--surface-muted)',
          header: 'var(--surface-header)',
        },
        ink: { DEFAULT: 'var(--text)', muted: 'var(--text-muted)' },
        muted: 'var(--text-muted)',
        edge: 'var(--border)',
        // ── 语义数据色：负荷/电量 ──
        load: {
          50: '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#4078aa',
          400: '#2e6ba4',
          500: '#175cd3',
          600: '#175cd3',
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a',
        },
        // ── 语义数据色：光伏/新能源 ──
        solar: {
          50: '#ecfdf5',
          100: '#d1fae5',
          200: '#a7f3d0',
          300: '#428c77',
          400: '#0f766e',
          500: '#0f766e',
          600: '#0f766e',
          700: '#047857',
          800: '#065f46',
          900: '#064e3b',
        },
        primary: {
          50: '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#77a4ed',
          400: '#377be0',
          500: '#175cd3',
          600: '#175cd3',
          700: '#114aa6',
          800: '#1e40af',
          900: '#1e3a8a',
          950: '#172554',
        },
        success: {
          50: '#ecfdf5',
          100: '#d1fae5',
          200: '#a7f3d0',
          300: '#448575',
          400: '#0f766e',
          500: '#0f766e',
          600: '#0f766e',
          700: '#047857',
        },
        warning: {
          50: '#fffbeb',
          100: '#fef3c7',
          200: '#fde68a',
          300: '#9a7427',
          400: '#9d7229',
          500: '#b17e27',
          600: '#92400e',
          700: '#b45309',
        },
        danger: {
          50: '#fef2f2',
          100: '#fee2e2',
          200: '#fecaca',
          300: '#a96368',
          400: '#b42318',
          500: '#b42318',
          600: '#b42318',
          700: '#b91c1c',
        },
        // 兼容现有组件命名；RGB 变量同时支持主题和透明度工具类。
        dark: {
          ...Object.fromEntries([50, 100, 200, 300, 400, 500, 600, 700, 750, 800, 850, 900, 950]
            .map(step => [step, `rgb(var(--tone-${step}) / <alpha-value>)`])),
        },
      },
      fontFamily: {
        sans: ['Microsoft YaHei', 'PingFang SC', 'Segoe UI', 'Arial', 'sans-serif'],
        mono: ['Consolas', 'Microsoft YaHei', 'monospace']
      },
      fontSize: {
        '2xs': ['0.625rem', { lineHeight: '0.75rem' }],
      },
      spacing: {
        18: '4.5rem',
        88: '22rem',
      },
      screens: {
        'xs': '475px',
        'sm': '640px',
        'md': '768px',
        'lg': '1024px',
        'xl': '1280px',
        '2xl': '1440px',
        '3xl': '1920px',
      },
      animation: {
        'fade-in': 'fade-in 300ms ease-out',
        'slide-up': 'slide-up 300ms ease-out',
        'scale-in': 'scale-in 200ms ease-out',
        'stagger-in': 'stagger-in 400ms ease-out backwards',
        'page-enter': 'page-enter 350ms ease-out',
        'counter-up': 'counter-up 600ms ease-out',
        'reveal-up': 'reveal-up 500ms ease-out backwards',
      },
      keyframes: {
        'fade-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        'slide-up': {
          from: { opacity: '0', transform: 'translateY(12px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'scale-in': {
          from: { opacity: '0', transform: 'scale(0.95)' },
          to: { opacity: '1', transform: 'scale(1)' },
        },
        'stagger-in': {
          from: { opacity: '0', transform: 'translateY(16px) scale(0.96)' },
          to: { opacity: '1', transform: 'translateY(0) scale(1)' },
        },
        'page-enter': {
          from: { opacity: '0', transform: 'translateY(8px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'counter-up': {
          from: { opacity: '0', transform: 'translateY(4px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'reveal-up': {
          from: { opacity: '0', transform: 'translateY(24px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
  darkMode: 'class'
}
