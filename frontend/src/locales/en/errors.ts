// Codici restituiti dal backend come HTTPException(detail={"code", "params"})
// — vedi app/api_errors.py. Ogni codice qui deve avere una controparte
// backend che lo solleva con esattamente questi nomi di parametro.
export const errors = {
  'errors.auth_already_configured': 'Login already configured.',
  'errors.auth_username_required': 'Username is required.',
  'errors.auth_password_too_short': 'Password must be at least 8 characters.',
  'errors.auth_invalid_credentials': 'Invalid credentials.',
  'errors.auth_required': 'Authentication required.',
  'errors.auth_wrong_current_password': 'Current password is incorrect.',

  'errors.poster_not_cached': 'Poster not cached.',

  'errors.disk_not_found': 'Disk {id} not found.',
  'errors.disk_root_path_unreachable': 'root_path is not reachable: {path}',
  'errors.disk_root_path_not_a_directory': 'root_path is not a reachable folder: {path}',
  'errors.disk_root_path_outside_scan_root': 'root_path must be inside disk_scan_root ({scan_root})',
  'errors.disk_root_path_conflict': 'A disk with root_path {path} already exists.',
  'errors.path_not_found': 'Path not found: {path}',
  'errors.folder_already_exists': 'Folder already exists: {path}',
  'errors.path_outside_scope': 'Path outside the allowed scope: {path}',

  'errors.run_not_found': 'Scan {id} not found.',
  'errors.media_item_not_found': 'This item is not in the library.',
  'errors.run_in_progress': 'A scan is in progress: try again when it has finished.',
  'errors.invalid_path': 'Invalid path.',
  'errors.run_already_finished': 'Scan {id} has already finished.',

  'errors.review_not_found': 'Review {id} not found.',
  'errors.seed_job_not_found': 'SeedJob {id} not found.',

  'errors.tracker_not_found': 'Tracker {id} not found.',
  'errors.tracker_adapter_type_unsupported': 'Unsupported adapter_type: {adapter_type} (supported: {supported})',
  'errors.tracker_no_upload_profile': 'Tracker {tracker} has no upload profile.',
  'errors.tracker_upload_profile_conflict': 'Tracker {id} already has an upload profile.',
  'errors.tracker_missing_announce_url': "Tracker '{tracker}' has no announce_url configured.",

  'errors.torrent_client_not_found': 'Torrent client {id} not found.',
  'errors.torrent_client_adapter_type_unsupported':
    'adapter_type not yet implemented: {adapter_type} (supported: {supported})',

  'errors.radarr_instance_not_found': 'Radarr instance {id} not found.',
  'errors.sonarr_instance_not_found': 'Sonarr instance {id} not found.',

  'errors.invalid_cron_expression': 'Invalid cron expression: {message}',

  'errors.upload_job_not_found': 'Upload {id} not found.',
  'errors.upload_job_wrong_status': "This can't be done while the upload is in status '{status}'.",
  'errors.upload_source_not_found': 'Source not found: {path}',
  'errors.upload_source_is_disk_root': 'Choose a file or a folder inside the disk, not the whole disk.',
  'errors.upload_source_unreadable': 'Could not read the source: {error}',
  'errors.upload_tracker_not_available': 'Tracker {id} is disabled or has no upload profile.',
  'errors.upload_no_trackers': 'Select at least one tracker with an upload profile.',
  'errors.upload_invalid_tmdb_id': 'Not a TMDB id: {value}',
  'errors.upload_invalid_imdb_id': 'Not an IMDB id: {value}',
  'errors.upload_kind_mismatch': "A {content_type} can't be uploaded as '{kind}'.",
  'errors.upload_season_required': 'Choose the season.',
  'errors.upload_single_season_required': 'An {kind} has exactly one season.',
  'errors.upload_episode_required': 'Choose the episode number.',
  'errors.upload_pack_requires_folder': 'A pack needs a folder as its source, not a single file.',
  'errors.upload_target_not_found': 'Tracker {id} is not part of this upload.',
  'errors.upload_dupe_not_found': 'Torrent {id} is not among the dupe-check results.',
  'errors.upload_dupe_no_download_link': "The tracker didn't give a download link for this torrent.",
  'errors.upload_invalid_override': 'Invalid value for {field}.',
  'errors.upload_unknown_override': 'Unknown field: {field}.',
  'errors.upload_invalid_action': '{tracker}: choose upload, reseed or skip.',
  'errors.upload_name_required': '{tracker}: the release name is empty.',
  'errors.upload_ids_required': '{tracker}: choose category, type and resolution.',
  'errors.upload_reseed_needs_identical': '{tracker}: a reseed needs an identical release on the tracker.',
  'errors.upload_target_busy': "{tracker} is still '{status}': wait for it to finish.",
  'errors.upload_decision_missing': '{tracker} has no decision.',
  'errors.upload_disk_missing': 'The disk of this upload no longer exists.',
  'errors.upload_no_seed_folder': 'Disk {disk} has no seeding or uploads folder configured.',
  'errors.upload_seed_folder_missing': 'The folder for uploads does not exist: {path}',
  'errors.upload_cross_device':
    'A hardlink cannot cross filesystems: {path} is on another device than the folder for uploads.',
  'errors.upload_seed_path_exists': 'A different file already exists at {path}.',
  'errors.upload_screenshots_failed': 'Could not make or upload the screenshots: {error}',
  'errors.upload_reseed_missing_video': "The tracker's torrent has a video Nazgarr can't find locally: {path}",
  'errors.upload_freeleech_not_allowed': '{tracker} does not allow a {value}% freeleech.',
  'errors.no_video_files': 'No video file found in the source.',
  'errors.invalid_content_type': 'Invalid content type: {value}',
  'errors.tmdb_not_found': 'Not found on TMDB.',
  'errors.tmdb_error': 'TMDB request failed: {error}',
  'errors.poster_not_available': 'No poster for this content.',

  'errors.tmdb_api_key_missing': 'tmdb_api_key not configured in app_settings (PUT /api/settings/tmdb_api_key).',
  'errors.image_host_unknown': 'Unknown image host in image_host_priority: {key}',
  'errors.no_image_host_configured':
    'No image host configured: set at least one api_key, or include Imgbox/Pixhost in image_host_priority '
    + "— they're the only two that don't require one.",
  'errors.bundled_profile_not_found': 'Bundled profile not found: {key}',
} as const
