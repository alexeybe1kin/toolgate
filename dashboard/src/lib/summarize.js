const TEMPLATES = {
  'resend.email.send': (a) => `Send email to ${a.to || '?'}${a.subject ? `: "${a.subject}"` : ''}`,
  'railway.deploy.trigger': (a) => `Deploy service ${a.service_id || '?'} to environment ${a.environment_id || '?'}`,
  'github.pr.create': (a) => `Open PR "${a.title || '?'}" (${a.head || '?'} → ${a.base || '?'})`,
  'github.issues.create': (a) => `Create issue "${a.title || '?'}" in ${a.owner || '?'}/${a.repo || '?'}`,
};

export function summarize(toolId, args) {
  return TEMPLATES[toolId]?.(args || {}) || `Call ${toolId}`;
}

export function formatTimeLeft(expiresAt) {
  const ms = new Date(expiresAt).getTime() - Date.now();
  if (ms <= 0) return 'expiring';
  const hours = Math.floor(ms / 3_600_000);
  const minutes = Math.floor((ms % 3_600_000) / 60_000);
  if (hours > 0) return `${hours}h ${minutes}m left`;
  return `${minutes}m left`;
}
