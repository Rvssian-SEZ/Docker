#!/bin/bash

# Simulates a download that streams progress for a while, hits a transient
# warning, and then fails outright - so CommandRunner's captured output is a
# realistic mix of PROGRESS_JSON lines and yt-dlp's own warning/error text,
# exercising strip_progress_lines/1's filtering on a failure.

echo 'PROGRESS_JSON:{"status": "downloading", "downloaded_bytes": 100, "total_bytes": 300}'
echo "WARNING: [youtube] some_id: some transient warning"
echo 'PROGRESS_JSON:{"status": "downloading", "downloaded_bytes": 200, "total_bytes": 300}'
echo "ERROR: [youtube] some_id: the actual failure reason"

exit 1
