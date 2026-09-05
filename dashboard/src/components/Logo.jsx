import { ShieldHalf } from 'lucide-react';

export default function Logo({ size = 'md' }) {
  const isSmall = size === 'sm';
  return (
    <div className="flex items-center gap-2">
      <span className="flex items-center justify-center rounded-md bg-accent/15 text-accent"
        style={{ width: isSmall ? 28 : 36, height: isSmall ? 28 : 36 }}>
        <ShieldHalf size={isSmall ? 16 : 20} strokeWidth={2.25} />
      </span>
      <span className={`font-semibold tracking-tight text-text ${isSmall ? 'text-base' : 'text-lg'}`}>
        ToolGate
      </span>
    </div>
  );
}
