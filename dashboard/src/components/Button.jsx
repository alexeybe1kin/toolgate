const VARIANTS = {
  primary: 'bg-accent text-white hover:bg-accent-hover',
  secondary: 'border border-border bg-transparent text-text hover:bg-white/[0.06]',
  danger: 'bg-red-500/15 text-red-400 hover:bg-red-500/25',
  ghost: 'text-muted hover:bg-white/[0.06] hover:text-text',
};

export default function Button({ variant = 'primary', className = '', children, ...props }) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-medium
                  transition-colors active:translate-y-px disabled:opacity-40 disabled:pointer-events-none
                  focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent
                  ${VARIANTS[variant]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

export function IconButton({ className = '', children, ...props }) {
  return (
    <button
      className={`inline-flex items-center justify-center rounded-md p-1.5 text-muted transition-colors
                  hover:bg-white/[0.06] hover:text-text disabled:opacity-40 disabled:pointer-events-none
                  focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent
                  ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}
