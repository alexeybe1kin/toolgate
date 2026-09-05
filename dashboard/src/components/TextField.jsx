export default function TextField({ label, className = '', ...props }) {
  return (
    <label className="block">
      {label && <span className="mb-1.5 block text-xs font-medium text-muted">{label}</span>}
      <input
        className={`w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-text
                    placeholder:text-muted/70 outline-none transition-colors focus-visible:border-accent
                    disabled:opacity-50 ${className}`}
        {...props}
      />
    </label>
  );
}
