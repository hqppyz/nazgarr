export const integrations = {
  'integrations.arrUsageDescription':
    'Read-only. On every scan, files these instances know are identified without a TMDB search, and orphan files are matched to the torrent they were imported from (from the history) without searching the tracker. Files are matched by folder, file name and exact size, so no path mapping is needed.',
  'integrations.autoApproveThresholdsTitle': 'Recommendation thresholds',
  'integrations.rematchTitle': 'Tracker search frequency',
  'integrations.rematchDescription':
    'An orphan file already searched on a tracker is not searched again on every scan: its candidates and review stay as they are until the file changes or this interval passes. Keeps scans from hitting tracker rate limits.',
  'integrations.rematchLabel': 'Search again after (days)',
  'integrations.rematchHelp': 'Default: 7. Use 0 to search every orphan on every scan.',
  'integrations.autoApproveThresholdsDescription':
    'A match at or above its threshold is marked as recommended in the review queue. Nothing is ever executed without your approval unless you turn on automatic execution below.',
  'integrations.executionTitle': 'Execution',
  'integrations.executionDescription':
    'What happens when a match is approved: how its data is checked, and whether recommended matches run on their own.',
  'integrations.skipRecheckLabel': "Skip the client's recheck when Nazgarr verified 100%",
  'integrations.skipRecheckHelp':
    "Off by default. When the full check has just verified every piece, with no extra file missing and the same info hash, the torrent is added to the client as already complete, without reading all the data a second time. In every other case the client rechecks as usual. There is a short window between the check and the add in which a file change would go unnoticed.",
  'integrations.skipRecheckNeedsVerify': 'Needs "Verify every piece before executing" to be on.',
  'integrations.verifyLabel': 'Verify every piece before executing',
  'integrations.verifyHelp':
    "On by default. When you approve a match, all of the torrent's pieces are checked against your files first, exactly like the client's recheck, and hardlinks and the torrent are added only if it will pass. Nothing is touched when the check fails. It reads the whole content, so large files take a few minutes. Turn it off to execute right away and rely on the sampled pieces checked during matching.",
  'integrations.autoExecuteLabel': 'Execute recommended matches automatically',
  'integrations.autoExecuteHelp':
    'Off by default. When on, every scan executes the recommended matches on its own: it creates hardlinks and adds torrents to your client (always with a full recheck) without asking. Leave it off to approve each one yourself.',

  'integrations.addInstance': 'Add instance',
  'integrations.addInstanceTitled': 'Add {name} instance',
  'integrations.editInstanceTitled': 'Edit {name} instance',
  'integrations.noInstances': 'No instances configured.',
  'integrations.instanceLabel': 'Label',
  'integrations.instanceUrl': 'URL',
  'integrations.urlSuggestion': 'e.g. {url}',
  'integrations.instanceApiKey': 'API key',
  'integrations.apiKeyHelp': 'Found in Settings → General in {name}.',
  'integrations.instanceEnabled': 'Enabled',
  'integrations.createInstanceFailed': 'Could not add instance: {message}',

  'integrations.priority': 'Priority',
  'integrations.priorityHelp': 'Higher values are queried first, once a resolver uses these.',
  'integrations.timeoutSeconds': 'Timeout (seconds)',
  'integrations.basicAuth': 'HTTP basic auth',
  'integrations.basicAuthDescription': 'For an instance sitting behind a reverse proxy with basic authentication.',
  'integrations.basicAuthUsername': 'Username',
  'integrations.basicAuthPassword': 'Password',
  'integrations.testConnection': 'Test connection',
  'integrations.connectedSuccess': 'Connected — v{version}.',
  'integrations.connectionFailed': 'Connection failed: {message}',
  'integrations.deleteInstanceTitle': 'Delete the instance {label}?',
  'integrations.deleteInstanceDescription': 'Nazgarr stops reading from this {name} instance. The instance itself is not touched.',
  'integrations.webhook.title':
    'Webhook',
  'integrations.webhook.dialogTitle':
    '{label} webhook',
  'integrations.webhook.description':
    'When {name} imports, upgrades, renames or deletes a file, Nazgarr updates just that file at once: no scan, only its disk wakes up, and the torrent it came from shows as linked right away.',
  'integrations.webhook.why':
    'The full scan stays, and also catches what the webhook cannot see (files copied by hand, events lost during a restart).',
  'integrations.webhook.enable':
    'Enable the webhook',
  'integrations.webhook.url':
    'URL',
  'integrations.webhook.password':
    'Password',
  'integrations.webhook.copy':
    'Copy {what}',
  'integrations.webhook.shownOnce':
    'The password is shown only now: if you lose it, regenerate it.',
  'integrations.webhook.step1':
    'In {name}: Settings › Connect › + › Webhook.',
  'integrations.webhook.step2':
    'Paste the URL, method POST; any username, and the password above.',
  'integrations.webhook.step3Radarr':
    'Turn on On Import, On Upgrade, On Rename and On Movie File Delete.',
  'integrations.webhook.step3Sonarr':
    'Turn on On Import, On Upgrade, On Rename and On Episode File Delete.',
  'integrations.webhook.step4':
    'Press Test and save: the event shows up here.',
  'integrations.webhook.reachability':
    'The URL is the one you are using to open Nazgarr: if {name} runs in another container, use the address it reaches Nazgarr at (e.g. http://nazgarr:3019).',
  'integrations.webhook.lastEvent':
    'Last event: {event}, {when} ({detail}).',
  'integrations.webhook.noEventYet':
    'Webhook on, no event received from {name} yet: press Test in its connection.',
  'integrations.webhook.regenerate':
    'Regenerate the password',
  'integrations.webhook.regenerateTitle':
    'Regenerate the webhook password?',
  'integrations.webhook.regenerateDescription':
    'The current one stops working at once: paste the new one in {name}.',
  'integrations.webhook.disable':
    'Disable',
  'integrations.webhook.disableTitle':
    'Disable the webhook?',
  'integrations.webhook.disableDescription':
    'Events from {name} will be refused: remove the connection from {name} too.',
  'integrations.webhook.searchLabel':
    'Search the trackers for a file just imported',
  'integrations.webhook.searchHelp':
    'For every instance. Off: a new file is searched at the next scan, as always.',
} as const
