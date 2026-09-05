import { useEffect } from 'react';
import { X } from 'lucide-react';

export default function Modal({ title, onClose, children, width = 'max-w-sm', flush = false }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title || 'ToolGate dialog'}
        className={`relative max-h-[calc(100svh-2rem)] w-full overflow-auto ${width} rounded-xl border border-border bg-surface ${flush ? 'p-0' : 'p-5'} shadow-2xl`}
      >
        {title && <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-medium text-text">{title}</h2>
          <button
            onClick={onClose}
            aria-label="Close dialog"
            className="rounded-md p-1 text-muted transition-colors hover:bg-white/[0.06] hover:text-text"
          >
            <X size={16} />
          </button>
        </div>}
        {!title && (
          <button onClick={onClose} aria-label="Close dialog" className="absolute right-4 top-4 z-10 rounded-md p-1.5 text-muted transition-colors hover:bg-white/[0.06] hover:text-text">
            <X size={17} />
          </button>
        )}
        {children}
      </div>
    </div>
  );
}
