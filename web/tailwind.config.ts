import type { Config } from 'tailwindcss';

const config: Config = {
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
          foreground: 'var(--bg)',
        },
        border: 'var(--border)',
        ring: 'var(--accent)',
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
