// Config type omitted: Tailwind v4 dropped `corePlugins` from the type, but the
// PostCSS plugin still reads and honors corePlugins at runtime.
const config = {
  content: [
    './app/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './lib/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        // Map project CSS variables to Tailwind's semantic color names
        // so shadcn/ui components that use `bg-primary`, `text-foreground` etc. work.
        background: 'var(--bg)',
        foreground: 'var(--text-primary)',
        primary: {
          DEFAULT: 'var(--accent)',
          foreground: 'var(--bg)',
        },
        secondary: {
          DEFAULT: 'var(--surface-2)',
          foreground: 'var(--text-secondary)',
        },
        muted: {
          DEFAULT: 'var(--surface-2)',
          foreground: 'var(--text-muted)',
        },
        destructive: {
          DEFAULT: 'var(--danger)',
          bg: 'var(--danger-bg)',
          foreground: 'var(--bg)',
        },
        success: {
          DEFAULT: 'var(--success)',
          bg: 'var(--success-bg)',
          foreground: 'var(--bg)',
        },
        warning: {
          DEFAULT: 'var(--warning)',
          bg: 'var(--warning-bg)',
          foreground: 'var(--bg)',
        },
        surface: {
          1: 'var(--surface-1)',
          2: 'var(--surface-2)',
          3: 'var(--surface-3)',
        },
        border: 'var(--border)',
        'border-strong': 'var(--border-strong)',
        ring: 'var(--accent)',
        'accent-bg': 'var(--accent-bg)',
      },
      borderRadius: {
        lg: '12px',
        md: '8px',
        sm: '6px',
      },
    },
  },
  // Preflight is a CSS reset — disabled because globals.css already handles it.
  corePlugins: { preflight: false },
  plugins: [],
};

export default config;
