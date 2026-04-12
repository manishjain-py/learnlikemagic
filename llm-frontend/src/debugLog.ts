/** Ships log lines to a local collector (port 9999) for CLI-side tailing.
 *  Also calls console.log so browser devtools still work.
 *  Safe to leave in — the POST silently fails if the collector isn't running. */
export function debugLog(msg: string) {
  console.log(msg);
  try {
    navigator.sendBeacon('http://localhost:9999', msg);
  } catch { /* collector not running — ignore */ }
}
