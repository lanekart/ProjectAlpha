const sensitivePatterns = [
  /(access_token=)[^&\s]+/gi,
  /(refresh_token=)[^&\s]+/gi,
  /(client_secret=)[^&\s]+/gi,
  /(code=)[^&\s]+/gi,
  /(authorization:\s*bearer\s+)[^\s]+/gi
];

export function redactSecrets(message: string): string {
  return sensitivePatterns.reduce((redacted, pattern) => {
    return redacted.replace(pattern, "$1[REDACTED]");
  }, message);
}
